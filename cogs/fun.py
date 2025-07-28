# cogs/fun.py
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import random

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.media_file = 'data/media.json'
        self.media = self.load_media()

    def load_media(self):
        if not os.path.exists(self.media_file):
            default_media = {
                "coinflip": {
                    "heads": ["https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExaDB6eXNqaGo3ZDA3ZGN5dWI4cTYyYjQ4ZWNmM3M1bnhkM3hhdXA4diZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o7bu12G12B4pX9G3C/giphy.gif"],
                    "tails": ["https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExaW14dGg2c3dma2R2b2s0bHNuZnJqbGowenEyeHVxY2NkcDN5dGdodyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/2w4p58o0eHn8Y1k3A6/giphy.gif"]
                },
                "diceroll": { "1": ["..."], "2": ["..."], "3": ["..."], "4": ["..."], "5": ["..."], "6": ["..."] } # Truncated for brevity
            }
            with open(self.media_file, 'w') as f:
                json.dump(default_media, f, indent=4)
            return default_media
        with open(self.media_file, 'r') as f:
            return json.load(f)

    def save_media(self):
        with open(self.media_file, 'w') as f:
            json.dump(self.media, f, indent=4)

    @app_commands.command(name='coinflip', description='Flips a coin. What else would it do?')
    async def coinflip(self, interaction: discord.Interaction):
        result = random.choice(['heads', 'tails'])
        image_url = random.choice(self.media['coinflip'][result])
        
        embed = discord.Embed(
            title="Coinflip Result",
            description=f"Hmph. It landed on **{result.capitalize()}**. Were you expecting something else?",
            color=discord.Color.gold()
        )
        embed.set_image(url=image_url)
        embed.set_footer(text=f"Flipped by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='diceroll', description='Rolls a six-sided die.')
    async def diceroll(self, interaction: discord.Interaction):
        result = str(random.randint(1, 6))
        # Ensure the dice roll images exist
        if result not in self.media['diceroll'] or not self.media['diceroll'][result]:
            await interaction.response.send_message("The admins haven't added an image for this roll yet. How boring.")
            return
        image_url = random.choice(self.media['diceroll'][result])
        
        embed = discord.Embed(
            title="Dice Roll Result",
            description=f"Fine, I'll roll it for you. You got a **{result}**. Don't bother me again.",
            color=discord.Color.purple()
        )
        embed.set_image(url=image_url)
        embed.set_footer(text=f"Rolled for {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='addmedia', description='[Admin] Adds media for coinflip or diceroll.')
    @app_commands.describe(category="The category to add to (coinflip or diceroll)", key="The key (heads, tails, or 1-6)", url="The image/GIF URL")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_media(self, interaction: discord.Interaction, category: str, key: str, url: str):
        category = category.lower()
        key = key.lower()
        if category not in self.media or key not in self.media[category]:
            await interaction.response.send_message("Ugh, that's not a valid category or key. Use `coinflip` (heads/tails) or `diceroll` (1-6).", ephemeral=True)
            return
        
        self.media[category][key].append(url)
        self.save_media()
        await interaction.response.send_message(f"I guess I'll add this one. Media added to `{category}` -> `{key}`.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Fun(bot))