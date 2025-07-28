import discord
from discord.ext import commands
from discord import app_commands
import random
import re
import asyncio
from typing import List

class FunCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Pre-compile regex for better performance
        self.dice_pattern = re.compile(r'^(\d+)d(\d+)$', re.IGNORECASE)
        
        # Constants for better maintainability
        self.COIN_STICKERS = [
            "https://media.discordapp.net/stickers/1377651154565206047.gif?size=256&name=misakacoin",
            "https://media.discordapp.net/stickers/1377651797484900462.gif?size=256&name=cointoss"
        ]
        self.DICE_STICKER = "https://media.discordapp.net/stickers/1377648107386441879.gif?size=256&name=dicethrow"
        
        # Animation timing
        self.ANIMATION_DELAY = 3  # Reduced from 5 seconds for better UX

    @app_commands.command(name="coinflip", description="Flip a coin!")
    async def coinflip(self, interaction: discord.Interaction):
        """Flip a coin and get heads or tails"""
        chosen_sticker = random.choice(self.COIN_STICKERS)
        
        # Create animation embed
        animation_embed = self._create_embed(
            title="🪙 Flipping Coin...",
            color=0xFFFF00,
            image_url=chosen_sticker
        )
        
        await interaction.response.send_message(embed=animation_embed)
        await asyncio.sleep(self.ANIMATION_DELAY)
        
        # Generate result
        result = random.choice(["Heads", "Tails"])
        color = 0x00FF00 if result == "Heads" else 0xFF0000
        
        # Create result embed
        result_embed = self._create_embed(
            title=f"🪙 Coin Flip Result: {result}!",
            color=color,
            image_url=chosen_sticker
        )
        
        await interaction.edit_original_response(embed=result_embed)

    @app_commands.command(name="roll", description="Roll custom dice (e.g., 1d6, 2d20)")
    @app_commands.describe(dice="Dice notation (e.g., 1d6, 2d20, 3d8)")
    async def roll_dice(self, interaction: discord.Interaction, dice: str):
        """Roll dice using standard dice notation (XdY format)"""
        
        # Validate and parse dice notation
        validation_result = self._validate_dice_input(dice)
        if not validation_result["valid"]:
            await interaction.response.send_message(
                f"❌ {validation_result['error']}",
                ephemeral=True
            )
            return
        
        num_dice, die_sides = validation_result["num_dice"], validation_result["die_sides"]
        
        # Show animation
        animation_embed = self._create_embed(
            title=f"🎲 Rolling {dice.upper()}...",
            color=0xFFFF00,
            image_url=self.DICE_STICKER
        )
        
        await interaction.response.send_message(embed=animation_embed)
        await asyncio.sleep(self.ANIMATION_DELAY)
        
        # Generate rolls
        rolls = [random.randint(1, die_sides) for _ in range(num_dice)]
        
        # Create result embed
        result_embed = self._create_dice_result_embed(dice, rolls, num_dice)
        await interaction.edit_original_response(embed=result_embed)

    def _create_embed(self, title: str, color: int, image_url: str = None) -> discord.Embed:
        """Helper method to create embeds consistently"""
        embed = discord.Embed(title=title, color=color)
        if image_url:
            embed.set_image(url=image_url)
        return embed

    def _validate_dice_input(self, dice: str) -> dict:
        """Validate dice input and return parsed values"""
        match = self.dice_pattern.match(dice.strip())
        
        if not match:
            return {
                "valid": False,
                "error": "Invalid dice format! Use format like `1d6`, `2d20`, etc."
            }
        
        num_dice = int(match.group(1))
        die_sides = int(match.group(2))
        
        if not (1 <= num_dice <= 100):
            return {
                "valid": False,
                "error": "Number of dice must be between 1 and 100!"
            }
        
        if not (2 <= die_sides <= 1000):
            return {
                "valid": False,
                "error": "Die sides must be between 2 and 1000!"
            }
        
        return {
            "valid": True,
            "num_dice": num_dice,
            "die_sides": die_sides
        }

    def _create_dice_result_embed(self, dice: str, rolls: List[int], num_dice: int) -> discord.Embed:
        """Create the dice result embed"""
        result_embed = discord.Embed(
            title=f"🎲 {dice.upper()} Results",
            color=0x3498DB
        )
        
        if num_dice == 1:
            result_embed.add_field(
                name="Result",
                value=f"**{rolls[0]}**",
                inline=False
            )
        else:
            # Use more efficient string joining
            rolls_str = ", ".join(str(roll) for roll in rolls)
            result_embed.add_field(
                name="Individual Rolls",
                value=rolls_str,
                inline=False
            )
            result_embed.add_field(
                name="Total",
                value=f"**{sum(rolls)}**",
                inline=False
            )
        
        result_embed.set_image(url=self.DICE_STICKER)
        return result_embed

async def setup(bot):
    await bot.add_cog(FunCommands(bot))