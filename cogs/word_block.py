# cogs/word_block.py
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import re

class WordBlock(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.blocklist_file = 'data/word_block.json'
        self.blocklist = self.load_blocklist()

    # Define the group as a class-level variable. This is the key.
    block = app_commands.Group(name="block", description="Manage your personal word blocklist.")

    def load_blocklist(self):
        if not os.path.exists(self.blocklist_file):
            return {}
        with open(self.blocklist_file, 'r') as f:
            return json.load(f)

    def save_blocklist(self):
        with open(self.blocklist_file, 'w') as f:
            json.dump(self.blocklist, f, indent=4)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.content.startswith('!'):
            return

        user_id = str(message.author.id)
        if user_id in self.blocklist:
            blocked_words = self.blocklist[user_id]
            for word in blocked_words:
                if re.search(r'\b' + re.escape(word) + r'\b', message.content, re.IGNORECASE):
                    try:
                        await message.delete()
                        await message.author.send(
                            f"H-hey! I had to delete your message in **{message.guild.name}** because it contained a word you blocked: `{word}`. J-just letting you know..."
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                    return

    @block.command(name='add', description="Adds a word to your personal blocklist.")
    @app_commands.describe(word="The word you want to block.")
    async def block_add(self, interaction: discord.Interaction, word: str):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        word = word.strip().lower()
        if not word:
            await interaction.followup.send("You can't block nothing. Don't waste my time.")
            return

        if user_id not in self.blocklist:
            self.blocklist[user_id] = []
        
        if word in self.blocklist[user_id]:
            await interaction.followup.send(f"You've already blocked `{word}`. Are you that forgetful?")
            return

        self.blocklist[user_id].append(word)
        self.save_blocklist()
        await interaction.followup.send(f"Fine. I'll block the word `{word}` for you. Don't come crying to me.")

    @block.command(name='remove', description="Removes a word from your blocklist.")
    @app_commands.describe(word="The word you want to unblock.")
    async def block_remove(self, interaction: discord.Interaction, word: str):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        word = word.strip().lower()
        
        if user_id not in self.blocklist or word not in self.blocklist[user_id]:
            await interaction.followup.send(f"You haven't even blocked the word `{word}`. Pay attention.")
            return

        self.blocklist[user_id].remove(word)
        if not self.blocklist[user_id]:
            del self.blocklist[user_id]
        self.save_blocklist()
        await interaction.followup.send(f"Okay, I've removed `{word}` from your blocklist. Try to keep up.")

    @block.command(name='list', description="Shows all the words you have blocked.")
    async def block_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        if user_id not in self.blocklist or not self.blocklist[user_id]:
            await interaction.followup.send("You haven't blocked any words. Surprising.")
            return

        blocked_words = ", ".join([f"`{w}`" for w in self.blocklist[user_id]])
        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Blocked Words",
            description=blocked_words,
            color=interaction.user.color
        )
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(WordBlock(bot))