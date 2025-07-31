import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
import random
import re
import asyncio
from typing import Dict, List, Literal, Optional

# Import our custom checks and utilities
from .bot_admin import BotAdmin
from utils.frustration_manager import get_frustration_level

# --- Self-Contained Personality for this Cog ---
PERSONALITY = {
    "coinflip_responses": [
        "Flipping a coin for you. It's **{result}**.",
        "Again? Fine. **{result}** this time.",
        "Are we going to do this all day? It's **{result}**.",
        "This is the last time. **{result}**. Now go do something productive."
    ],
    "rps_win": "You chose **{user_choice}** and I chose **{bot_choice}**. Hmph. You win this time.",
    "rps_lose": "You chose **{user_choice}** and I chose **{bot_choice}**. Predictable. I win.",
    "rps_tie": "We both chose **{user_choice}**. How boring.",
    "embed_added": "Fine, I've added that image to the `{command}` list. I hope it's a good one.",
    "embed_invalid_url": "That doesn't look like a real URL. Try again.",
    "error_roll_format": "That's not how you roll dice. Use the format `1d6` or `2d20`."
}


class FunCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.embeds_file = Path("data/fun_embeds.json")
        self.settings_file = Path("data/fun_settings.json")
        
        self.embed_data: Dict[str, Dict[str, List[str]]] = self._load_json(self.embeds_file)
        # Data: {guild_id: {"roll_gifs_disabled": [user_id, ...]}}
        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        
        self.default_embeds = {
            "coinflip": ["https://media1.tenor.com/m/gT2UI5h7-4sAAAAC/coin-flip-heads.gif"],
            "roll": ["https://media1.tenor.com/m/Z2WSYMOa2oYAAAAC/dice-roll.gif"],
            "rps": ["https://media1.tenor.com/m/y6gH0Q5i3iMAAAAC/rock-paper-scissors-anime.gif"]
        }
        self.dice_pattern = re.compile(r'(\d+)d(\d+)', re.IGNORECASE)

    def _load_json(self, file_path: Path) -> Dict:
        if not file_path.exists(): return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError):
            self.logger.error(f"Error loading {file_path}", exc_info=True)
            return {}

    async def _save_json(self, data: dict, file_path: Path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except IOError:
            self.logger.error(f"Error saving {file_path}", exc_info=True)

    def _get_random_embed_url(self, guild_id: int, command: str) -> str:
        urls = self.embed_data.get(str(guild_id), {}).get(command, [])
        return random.choice(urls) if urls else random.choice(self.default_embeds[command])

    # --- Fun Commands ---
    @app_commands.command(name="coinflip", description="Flip a coin.")
    async def coinflip(self, interaction: discord.Interaction):
        flipping_url = self._get_random_embed_url(interaction.guild_id, "coinflip")
        embed = discord.Embed(title="Flipping coin...", color=discord.Color.gold())
        embed.set_image(url=flipping_url)
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(2)
        frustration = get_frustration_level(self.bot, interaction)
        response_index = min(frustration, len(PERSONALITY["coinflip_responses"]) - 1)
        result = random.choice(["Heads", "Tails"])
        response_template = PERSONALITY["coinflip_responses"][response_index]
        color = discord.Color.green() if result == "Heads" else discord.Color.red()
        result_embed = discord.Embed(title=f"🪙 Coin Flip Result: {result}!", description=response_template.format(result=result), color=color)
        result_embed.set_image(url=flipping_url)
        await interaction.edit_original_response(embed=result_embed)

    @app_commands.command(name="roll", description="Roll one or more dice (e.g., 1d6, 2d20).")
    @app_commands.describe(
        dice="The dice to roll in XdY format.",
        show_gif="Whether to show a GIF. Defaults to your last choice (or ON)."
    )
    async def roll(self, interaction: discord.Interaction, dice: str, show_gif: Optional[bool] = None):
        match = self.dice_pattern.match(dice.lower().strip())
        if not match:
            return await interaction.response.send_message(PERSONALITY["error_roll_format"], ephemeral=True)

        num_dice, num_sides = int(match.group(1)), int(match.group(2))
        if not (1 <= num_dice <= 50 and 2 <= num_sides <= 1000):
            return await interaction.response.send_message("You can roll 1-50 dice with 2-1000 sides each.", ephemeral=True)

        rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
        total = sum(rolls)
        
        guild_id, user_id = str(interaction.guild_id), interaction.user.id
        disabled_list = self.settings_data.setdefault(guild_id, {}).setdefault("roll_gifs_disabled", [])

        # --- NEW LOGIC: Determine display style and save preference ---
        display_gif = True
        if show_gif is not None: # User explicitly chose
            display_gif = show_gif
            # Save the user's new preference
            if display_gif and user_id in disabled_list:
                disabled_list.remove(user_id)
                await self._save_json(self.settings_data, self.settings_file)
            elif not display_gif and user_id not in disabled_list:
                disabled_list.append(user_id)
                await self._save_json(self.settings_data, self.settings_file)
        else: # User did not specify, use their saved preference
            display_gif = user_id not in disabled_list
        
        if display_gif:
            # The original behavior with the GIF
            embed_url = self._get_random_embed_url(interaction.guild_id, "roll")
            embed = discord.Embed(
                title=f"🎲 Rolled {dice}: Result is {total}",
                description=f"Individual rolls: `{'`, `'.join(map(str, rolls))}`" if num_dice > 1 else "",
                color=discord.Color.blue()
            )
            embed.set_image(url=embed_url)
        else:
            # The new, compact, text-based embed
            rolls_str = ' '.join(map(str, rolls))
            description = (
                f"```┌─────────┬───────┐\n"
                f"│ {dice:<7} │ rolls │ sum   │\n"
                f"├─────────┼───────┤\n"
                f"│ {rolls_str:<7} │ {total:<5} │\n"
                f"└─────────┴───────┘```"
            )
            embed = discord.Embed(description=description, color=discord.Color.blue())

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rps", description="Play Rock, Paper, Scissors against me.")
    @app_commands.describe(choice="Your choice.")
    @app_commands.choices(choice=[app_commands.Choice(name="Rock", value="rock"), app_commands.Choice(name="Paper", value="paper"), app_commands.Choice(name="Scissors", value="scissors"),])
    async def rps(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        user_choice = choice.value
        bot_choice = random.choice(["rock", "paper", "scissors"])
        if user_choice == bot_choice:
            result_text = PERSONALITY["rps_tie"].format(user_choice=user_choice)
            color = discord.Color.light_gray()
        elif (user_choice == "rock" and bot_choice == "scissors") or (user_choice == "scissors" and bot_choice == "paper") or (user_choice == "paper" and bot_choice == "rock"):
            result_text = PERSONALITY["rps_win"].format(user_choice=user_choice.title(), bot_choice=bot_choice)
            color = discord.Color.green()
        else:
            result_text = PERSONALITY["rps_lose"].format(user_choice=user_choice.title(), bot_choice=bot_choice)
            color = discord.Color.red()
        embed_url = self._get_random_embed_url(interaction.guild_id, "rps")
        embed = discord.Embed(description=result_text, color=color)
        embed.set_image(url=embed_url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="funembeds", description="Add a new image/GIF for a fun command.")
    @app_commands.describe(command="The command to add the image to.", url="The direct URL of the image or GIF.")
    @app_commands.choices(command=[app_commands.Choice(name="Coinflip", value="coinflip"), app_commands.Choice(name="Roll", value="roll"), app_commands.Choice(name="RPS", value="rps"),])
    @BotAdmin.is_bot_admin()
    async def funembeds(self, interaction: discord.Interaction, command: app_commands.Choice[str], url: str):
        if not (url.startswith("http://") or url.startswith("https://")):
            return await interaction.response.send_message(PERSONALITY["embed_invalid_url"], ephemeral=True)
        guild_id, command_name = str(interaction.guild_id), command.value
        self.embed_data.setdefault(guild_id, {})
        self.embed_data[guild_id].setdefault(command_name, [])
        self.embed_data[guild_id][command_name].append(url)
        await self._save_json(self.embed_data, self.embeds_file)
        response = PERSONALITY["embed_added"].format(command=command.name)
        await interaction.response.send_message(response, ephemeral=True)

async def setup(bot):
    await bot.add_cog(FunCommands(bot))