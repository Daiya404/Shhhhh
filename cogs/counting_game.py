# cogs/counting_game.py
import discord
from discord import app_commands
from discord.ext import commands
import json
import os

class CountingGame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.counting_file = 'data/counting_game.json'
        self.game_data = self._load_data()

    def _load_data(self):
        """Loads game data from file, creating it if it doesn't exist."""
        if not os.path.exists(self.counting_file):
            default = {
                "channel_id": None, 
                "current_number": 0, 
                "last_user_id": None,
                "leaderboard": {},
                "pinned_message_id": None
            }
            with open(self.counting_file, 'w') as f:
                json.dump(default, f, indent=4)
            return default
        with open(self.counting_file, 'r') as f:
            return json.load(f)

    def _save_data(self):
        """Saves game data to file."""
        with open(self.counting_file, 'w') as f:
            json.dump(self.game_data, f, indent=4)

    async def _update_pinned_message(self, channel: discord.TextChannel, final_message: str = None):
        """Updates the pinned status message."""
        if not self.game_data.get("pinned_message_id"):
            return

        try:
            msg = await channel.fetch_message(self.game_data["pinned_message_id"])
            
            embed = discord.Embed(
                title="🔢 Counting Game Status",
                description="The rules are simple: count up by one. Don't post twice in a row.",
                color=discord.Color.green()
            )
            embed.add_field(name="Current Number", value=f"**{self.game_data['current_number']}**", inline=False)
            
            last_user = "Nobody yet"
            if self.game_data.get("last_user_id"):
                try:
                    user = await self.bot.fetch_user(self.game_data["last_user_id"])
                    last_user = user.mention
                except discord.NotFound:
                    last_user = "An unknown user"

            embed.add_field(name="Last Successful Count By", value=last_user, inline=False)
            
            if final_message:
                embed.set_footer(text=final_message)

            await msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException) as e:
            print(f"Failed to update pinned counting message: {e}")
            self.game_data["pinned_message_id"] = None # Invalidate if message is gone
            self._save_data()
            await channel.send("I couldn't find my pinned message! An admin might need to run `/counting start` again to fix me.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots and messages not in the game channel
        if message.author.bot or self.game_data["channel_id"] != message.channel.id:
            return

        # Ignore commands
        if message.content.startswith('/'): # Checking for slash command usage
            return

        channel = message.channel
        try:
            number = int(message.content)
            expected_number = self.game_data["current_number"] + 1
            
            # Rule 1: Cannot count twice in a row
            if message.author.id == self.game_data["last_user_id"]:
                error_embed = discord.Embed(title="Hold on a second!", description=f"Not so fast, {message.author.mention}. Let someone else have a turn.", color=discord.Color.orange())
                await channel.send(embed=error_embed, delete_after=10)
                await message.add_reaction("⏳")
                return

            # Rule 2: Must be the correct number
            if number == expected_number:
                self.game_data["current_number"] = number
                self.game_data["last_user_id"] = message.author.id
                
                user_id_str = str(message.author.id)
                self.game_data["leaderboard"][user_id_str] = self.game_data["leaderboard"].get(user_id_str, 0) + 1
                
                self._save_data()
                await message.add_reaction("✅")
                await self._update_pinned_message(channel)
            else: # Wrong number, reset the game
                await message.add_reaction("❌")
                fail_message = f"Oh, look who can't count. {message.author.mention} broke the chain at **{self.game_data['current_number']}**! The next number was `{expected_number}`. Back to **0** we go. Thanks a lot."
                self.game_data["current_number"] = 0
                self.game_data["last_user_id"] = None
                self._save_data()
                
                fail_embed = discord.Embed(title="Chain Broken!", description=fail_message, color=discord.Color.red())
                await channel.send(embed=fail_embed)
                await self._update_pinned_message(channel, final_message="The chain was just broken!")

        except ValueError: # Message was not a number
            error_embed = discord.Embed(title="That's not a number!", description=f"{message.author.mention}, we're counting here. Try again with an actual number.", color=discord.Color.orange())
            await channel.send(embed=error_embed, delete_after=10)
            await message.add_reaction("❓")

    @app_commands.command(name="countingstart", description="[Admin] Sets up the counting game in a channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def counting_start(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)

        self.game_data = self._load_data() # Reload data
        self.game_data["channel_id"] = channel.id
        self.game_data["current_number"] = 0
        self.game_data["last_user_id"] = None
        
        status_embed = discord.Embed(title="🔢 Counting Game Started!", description="Let's see how high you can count. I'll keep track here.", color=discord.Color.green())
        status_embed.add_field(name="Current Number", value="**0**", inline=False)
        status_embed.add_field(name="Next Number", value="**1**", inline=False)
        status_embed.set_footer(text="Good luck. You'll need it.")

        try:
            status_message = await channel.send(embed=status_embed)
            await status_message.pin()
            self.game_data["pinned_message_id"] = status_message.id
            self._save_data()
            await interaction.followup.send(f"Done. I've set up the counting game in {channel.mention}. I even pinned a message for you all.")
        except discord.Forbidden:
            await interaction.followup.send("I can't start the game. I'm missing the 'Manage Messages' permission, which I need to pin my status.")
        except Exception as e:
            await interaction.followup.send(f"An unexpected error occurred: {e}")

    @app_commands.command(name="countboard", description="Shows the counting game leaderboard.")
    async def count_board(self, interaction: discord.Interaction):
        if not self.game_data.get("leaderboard"):
            await interaction.response.send_message("The leaderboard is empty. No one is even trying.")
            return
        
        sorted_board = sorted(self.game_data["leaderboard"].items(), key=lambda item: item[1], reverse=True)
        
        embed = discord.Embed(title="Counting Game Leaderboard", description="Who has contributed the most numbers?", color=discord.Color.green())
        board_text = ""
        for i, (user_id, score) in enumerate(sorted_board[:10]):
            try:
                user = await self.bot.fetch_user(int(user_id))
                user_name = user.display_name
            except discord.NotFound:
                user_name = f"Unknown User"
            board_text += f"**{i+1}.** {user_name} - {score} numbers\n"
        
        embed.description = board_text
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CountingGame(bot))