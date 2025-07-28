# cogs/anime_game.py
import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import random
import aiohttp

class AnimeGame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.game_file = 'data/anime_game.json'
        self.game_data = self._load_data()
        self.current_letter = self.game_data.get("current_letter")
        self.letter_weights = { 'a': 10, 'b': 8, 'c': 8, 'd': 7, 'e': 8, 'f': 6, 'g': 7, 'h': 8, 'i': 7, 'j': 6, 'k': 9, 'l': 6, 'm': 9, 'n': 7, 'o': 7, 'p': 5, 'q': 1, 'r': 8, 's': 9, 't': 8, 'u': 5, 'v': 3, 'w': 4, 'x': 1, 'y': 6, 'z': 2 }
        if self.game_data.get("is_active"):
            self.change_letter_loop.change_interval(minutes=self.game_data.get("frequency", 15))
            self.change_letter_loop.start()

    # Define the group here
    animegame = app_commands.Group(name="animegame", description="Commands to manage the anime character game.")

    def _load_data(self):
        # ... (rest of the file is the same, this function does not change)
        if not os.path.exists(self.game_file):
            default = { "channel_id": None, "is_active": False, "frequency": 15, "used_names": [], "scores": {}, "pinned_message_id": None, "current_letter": None, "last_winner_id": None, "last_answer": "" }
            with open(self.game_file, 'w') as f: json.dump(default, f, indent=4)
            return default
        with open(self.game_file, 'r') as f: return json.load(f)

    def _save_data(self):
        # ... (no change)
        with open(self.game_file, 'w') as f: json.dump(self.game_data, f, indent=4)
    
    async def _update_pinned_message(self, channel: discord.TextChannel, new_letter: bool = False):
        # ... (no change)
        if not self.game_data.get("pinned_message_id"): return
        try:
            msg = await channel.fetch_message(self.game_data["pinned_message_id"])
            title = "🔥 New Letter! 🔥" if new_letter else "🎭 Anime Character Game"
            embed = discord.Embed(title=title, description="Give me the full name of an anime character starting with the letter below.", color=discord.Color.red())
            embed.add_field(name="Current Letter", value=f"**{self.current_letter.upper()}**", inline=True)
            last_winner_str = "No one yet..."
            if self.game_data.get("last_winner_id"):
                try: user = await self.bot.fetch_user(self.game_data["last_winner_id"]); last_winner_str = f"**{self.game_data.get('last_answer')}** by {user.mention}"
                except discord.NotFound: last_winner_str = f"**{self.game_data.get('last_answer')}** by an unknown user"
            embed.add_field(name="Last Correct Answer", value=last_winner_str, inline=False)
            top_player_str = "The field is wide open."
            if self.game_data["scores"]:
                top_id, top_score = sorted(self.game_data["scores"].items(), key=lambda x: x[1], reverse=True)[0]
                try: top_user = await self.bot.fetch_user(int(top_id)); top_player_str = f"{top_user.mention} with {top_score} points"
                except discord.NotFound: top_player_str = f"An unknown user with {top_score} points"
            embed.add_field(name="Current Leader", value=top_player_str, inline=False)
            embed.set_footer(text=f"A new letter appears every {self.game_data.get('frequency', 15)} minutes. Use /animegame leaderboard to see scores.")
            await msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException): pass

    async def _query_anilist(self, name: str):
        # ... (no change)
        query = 'query ($search: String) { Character (search: $search) { id name { full native } } }'
        async with aiohttp.ClientSession() as session:
            async with session.post('https://graphql.anilist.co', json={'query': query, 'variables': {'search': name}}) as resp:
                if resp.status == 200: return await resp.json()
                return None

    @tasks.loop(minutes=15)
    async def change_letter_loop(self):
        # ... (no change)
        if self.game_data.get("channel_id") and self.game_data.get("is_active"):
            channel = self.bot.get_channel(self.game_data["channel_id"])
            if channel:
                population = [val for val, count in self.letter_weights.items() for _ in range(count)]
                self.current_letter = random.choice(population)
                self.game_data["current_letter"] = self.current_letter
                self._save_data()
                await self._update_pinned_message(channel, new_letter=True)

    @change_letter_loop.before_loop
    async def before_change_letter_loop(self):
        # ... (no change)
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ... (no change)
        if message.author.bot or not self.game_data.get("is_active") or self.game_data["channel_id"] != message.channel.id or message.content.startswith('/'): return
        name = message.content.strip()
        if not self.current_letter or not name.lower().startswith(self.current_letter): await message.add_reaction("❌"); return
        normalized_name = name.lower()
        if normalized_name in self.game_data["used_names"]: await message.reply(embed=discord.Embed(description=f"Too slow. Someone already said that.", color=discord.Color.orange()), delete_after=7); return
        result = await self._query_anilist(name)
        if result and result['data']['Character']:
            char_data = result['data']['Character']; char_name_full = char_data['name']['full'].lower(); name_parts = char_name_full.split(); reversed_char_name = " ".join(reversed(name_parts))
            if normalized_name == char_name_full or normalized_name == reversed_char_name:
                user_id = str(message.author.id); self.game_data["scores"][user_id] = self.game_data["scores"].get(user_id, 0) + 1; self.game_data["used_names"].extend([char_name_full, reversed_char_name]); self.game_data["last_winner_id"] = message.author.id; self.game_data["last_answer"] = char_data['name']['full']; self._save_data()
                await message.add_reaction("✅"); await self._update_pinned_message(message.channel)
            else: await message.reply(embed=discord.Embed(description=f"I found `{char_data['name']['full']}`, but that doesn't perfectly match what you said. Precision is key.", color=discord.Color.orange()), delete_after=10)
        else: await message.reply(embed=discord.Embed(description=f"`{name}`? Are you making that up? I couldn't find them.", color=discord.Color.orange()), delete_after=7)

    @animegame.command(name="start", description="[Admin] Starts the anime game in a channel.")
    @app_commands.describe(channel="The channel to play in.", frequency="How often (in minutes) the letter should change.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def start_game(self, interaction: discord.Interaction, channel: discord.TextChannel, frequency: int = 15):
        await interaction.response.defer(ephemeral=True)
        self.game_data.update({"channel_id": channel.id, "is_active": True, "frequency": frequency})
        self.change_letter_loop.change_interval(minutes=frequency)
        if not self.change_letter_loop.is_running(): self.change_letter_loop.start()
        initial_embed = discord.Embed(title="🎭 Anime Character Game Started!", color=discord.Color.red())
        try:
            msg = await channel.send(embed=initial_embed); await msg.pin(); self.game_data["pinned_message_id"] = msg.id; self._save_data(); await self.change_letter_loop.coro(self)
            await interaction.followup.send(f"The game is afoot! I've set everything up in {channel.mention}.")
        except discord.Forbidden: await interaction.followup.send("I can't start the game. I need 'Manage Messages' permission to pin my status.")

    @animegame.command(name="stop", description="[Admin] Stops the anime game.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def stop_game(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.change_letter_loop.stop()
        if self.game_data.get("channel_id") and self.game_data.get("pinned_message_id"):
            try: channel = self.bot.get_channel(self.game_data["channel_id"]); msg = await channel.fetch_message(self.game_data["pinned_message_id"]); await msg.unpin()
            except (discord.NotFound, discord.Forbidden): pass
        self.game_data.update({"is_active": False, "pinned_message_id": None}); self._save_data()
        await interaction.followup.send("Hmph. Game over, I guess. I've stopped the timer and unpinned my message.")

    @animegame.command(name="leaderboard", description="Shows the top players in the anime game.")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.game_data["scores"]: await interaction.followup.send("No one has any points. How pathetic."); return
        sorted_scores = sorted(self.game_data["scores"].items(), key=lambda item: item[1], reverse=True)
        embed = discord.Embed(title="Anime Game Leaderboard", color=discord.Color.blue()); description = ""
        for i, (user_id, score) in enumerate(sorted_scores[:10]):
            try: user = await self.bot.fetch_user(int(user_id)); user_name = user.display_name
            except discord.NotFound: user_name = f"An Unknown Weeb"
            description += f"**{i+1}.** {user_name} - {score} points\n"
        embed.description = description
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(AnimeGame(bot))