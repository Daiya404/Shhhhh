# --- plugins/entertainment/quick_games_plugin.py ---

import discord
from discord import app_commands
import random
import re
import asyncio

from plugins.base_plugin import BasePlugin

class QuickGamesPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "quick_games"

    def __init__(self, bot):
        super().__init__(bot)
        self.dice_pattern = re.compile(r'(\d+)d(\d+)', re.IGNORECASE)
        # Default GIFs for when no custom ones are set
        self.default_embeds = {
            "coinflip": "https://media1.tenor.com/m/gT2UI5h7-4sAAAAC/coin-flip-heads.gif",
            "roll": "https://media1.tenor.com/m/Z2WSYMOa2oYAAAAC/dice-roll.gif",
            "rps": "https://media1.tenor.com/m/y6gH0Q5i3iMAAAAC/rock-paper-scissors-anime.gif"
        }

    async def _get_random_embed_url(self, guild_id: int, command: str) -> str:
        """Gets a custom embed URL from the database, or returns a default."""
        guild_data = await self.db.get_guild_data(guild_id, self.name)
        urls = guild_data.get("embed_urls", {}).get(command, [])
        return random.choice(urls) if urls else self.default_embeds[command]

    @app_commands.command(name="coinflip", description="Flip a coin.")
    async def coinflip(self, interaction: discord.Interaction):
        result = random.choice(["Heads", "Tails"])
        flipping_url = await self._get_random_embed_url(interaction.guild_id, "coinflip")

        embed = discord.Embed(title="Flipping coin...", color=discord.Color.gold())
        embed.set_image(url=flipping_url)
        await interaction.response.send_message(embed=embed)

        await asyncio.sleep(2) # Dramatic effect

        result_embed = discord.Embed(
            title=f"🪙 It's {result}!",
            color=discord.Color.green() if result == "Heads" else discord.Color.red()
        )
        result_embed.set_image(url=flipping_url)
        await interaction.edit_original_response(embed=result_embed)

    @app_commands.command(name="roll", description="Roll one or more dice (e.g., 1d6, 2d20).")
    @app_commands.describe(dice="The dice to roll in XdY format.")
    async def roll(self, interaction: discord.Interaction, dice: str):
        match = self.dice_pattern.match(dice.lower().strip())
        if not match:
            return await interaction.response.send_message("That's not how you roll dice. Use the format `1d6` or `2d20`.", ephemeral=True)

        num_dice, num_sides = int(match.group(1)), int(match.group(2))
        if not (1 <= num_dice <= 50 and 2 <= num_sides <= 1000):
            return await interaction.response.send_message("You can roll 1-50 dice with 2-1000 sides each.", ephemeral=True)

        rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
        total = sum(rolls)
        roll_url = await self._get_random_embed_url(interaction.guild_id, "roll")

        embed = discord.Embed(
            title=f"🎲 Rolled {dice}: Result is {total}",
            description=f"Individual rolls: `{'`, `'.join(map(str, rolls))}`" if num_dice > 1 else "",
            color=discord.Color.blue()
        )
        embed.set_image(url=roll_url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rps", description="Play Rock, Paper, Scissors against me.")
    @app_commands.describe(choice="Your choice.")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Rock", value="rock"),
        app_commands.Choice(name="Paper", value="paper"),
        app_commands.Choice(name="Scissors", value="scissors"),
    ])
    async def rps(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        user_choice = choice.value
        bot_choice = random.choice(["rock", "paper", "scissors"])
        rps_url = await self._get_random_embed_url(interaction.guild_id, "rps")

        if user_choice == bot_choice:
            result_text, color = f"We both chose **{user_choice}**. A draw.", discord.Color.light_gray()
        elif (user_choice, bot_choice) in [("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")]:
            result_text, color = f"You chose **{user_choice}** and I chose **{bot_choice}**. You win.", discord.Color.green()
        else:
            result_text, color = f"You chose **{user_choice}** and I chose **{bot_choice}**. I win.", discord.Color.red()

        embed = discord.Embed(description=result_text, color=color)
        embed.set_image(url=rps_url)
        await interaction.response.send_message(embed=embed)