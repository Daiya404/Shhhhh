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
from .bot_admin import BotAdmin
from utils.frustration_manager import get_frustration_level

# Personality for this Cog
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
    "embed_added": "Fine, I've added that image to the `{command}` list for this server. I hope it's a good one.",
    "embed_invalid_url": "That doesn't look like a real URL. Try again.",
    "error_roll_format": "That's not how you roll dice. Use the format `1d6` or `2d20`.",
    "no_gif_sources": "No GIF sources available. Using default GIFs.",
    "gif_source_set": "GIF source set to **{guild_name}** for {command} command.",
    "invalid_gif_source": "That server doesn't have any GIFs for this command, or I don't have access to it.",
    "gif_source_reset": "GIF source reset to default for {command} command."
}


class GifSourceSelect(discord.ui.Select):
    def __init__(self, fun_cog, user_id: int, command: str, available_guilds: Dict[str, str]):
        self.fun_cog = fun_cog
        self.user_id = user_id
        self.command = command
        
        options = [
            discord.SelectOption(
                label="Default GIFs",
                value="default",
                description="Use built-in default GIFs",
                emoji="🎲"
            )
        ]
        
        # Add guild options (limit to 24 to stay under Discord's 25 option limit)
        for guild_id, guild_name in list(available_guilds.items())[:24]:
            options.append(
                discord.SelectOption(
                    label=guild_name[:100],  # Discord limit
                    value=guild_id,
                    description=f"Use GIFs from {guild_name}"[:100],
                    emoji="🏠"
                )
            )
        
        super().__init__(placeholder="Choose GIF source...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your selection menu.", ephemeral=True)
        
        selected_value = self.values[0]
        
        # Load user preferences
        user_prefs = self.fun_cog.user_preferences.setdefault(str(self.user_id), {})
        
        if selected_value == "default":
            # Reset to default
            user_prefs.pop(self.command, None)
            await self.fun_cog._save_json(self.fun_cog.user_preferences, self.fun_cog.user_prefs_file)
            response = PERSONALITY["gif_source_reset"].format(command=self.command)
        else:
            # Set to specific guild
            # Validate the guild has GIFs for this command
            if selected_value not in self.fun_cog.embed_data or self.command not in self.fun_cog.embed_data[selected_value]:
                return await interaction.response.send_message(PERSONALITY["invalid_gif_source"], ephemeral=True)
            
            guild_name = next((name for gid, name in self.view.available_guilds.items() if gid == selected_value), "Unknown Server")
            user_prefs[self.command] = selected_value
            await self.fun_cog._save_json(self.fun_cog.user_preferences, self.fun_cog.user_prefs_file)
            response = PERSONALITY["gif_source_set"].format(guild_name=guild_name, command=self.command)
        
        await interaction.response.edit_message(content=response, view=None)


class GifSourceView(discord.ui.View):
    def __init__(self, fun_cog, user_id: int, command: str, available_guilds: Dict[str, str]):
        super().__init__(timeout=60)
        self.available_guilds = available_guilds
        self.add_item(GifSourceSelect(fun_cog, user_id, command, available_guilds))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class FunCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.embeds_file = Path("data/fun_embeds.json")
        self.settings_file = Path("data/fun_settings.json")
        self.user_prefs_file = Path("data/user_gif_preferences.json")
        
        self.embed_data: Dict[str, Dict[str, List[str]]] = self._load_json(self.embeds_file)
        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        self.user_preferences: Dict[str, Dict[str, str]] = self._load_json(self.user_prefs_file)
        
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

    def _get_random_embed_url(self, user_id: int, command: str) -> str:
        """Get a random embed URL based on user preferences or defaults."""
        # Check user preferences first
        user_prefs = self.user_preferences.get(str(user_id), {})
        preferred_guild = user_prefs.get(command)
        
        if preferred_guild and preferred_guild in self.embed_data:
            urls = self.embed_data[preferred_guild].get(command, [])
            if urls:
                return random.choice(urls)
        
        # Fall back to defaults
        return random.choice(self.default_embeds[command])

    def _get_available_gif_guilds(self, command: str) -> Dict[str, str]:
        """Get all guilds that have GIFs for the specified command."""
        available_guilds = {}
        
        for guild_id, commands_data in self.embed_data.items():
            if command in commands_data and commands_data[command]:
                try:
                    guild = self.bot.get_guild(int(guild_id))
                    if guild:
                        available_guilds[guild_id] = guild.name
                except (ValueError, AttributeError):
                    continue
        
        return available_guilds

    @app_commands.command(name="coinflip", description="Flip a coin.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def coinflip(self, interaction: discord.Interaction):
        flipping_url = self._get_random_embed_url(interaction.user.id, "coinflip")
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
        show_gif="Whether to show a GIF. Remembers your last choice."
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def roll(self, interaction: discord.Interaction, dice: str, show_gif: Optional[bool] = None):
        match = self.dice_pattern.match(dice.lower().strip())
        if not match:
            return await interaction.response.send_message(PERSONALITY["error_roll_format"], ephemeral=True)

        num_dice, num_sides = int(match.group(1)), int(match.group(2))
        if not (1 <= num_dice <= 50 and 2 <= num_sides <= 1000):
            return await interaction.response.send_message("You can roll 1-50 dice with 2-1000 sides each.", ephemeral=True)

        rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
        total = sum(rolls)
        
        # Handle GIF preferences per user instead of per guild
        user_id = interaction.user.id
        user_settings = self.settings_data.setdefault("users", {}).setdefault(str(user_id), {})
        disabled_gifs = user_settings.get("roll_gifs_disabled", False)

        display_gif = True
        if show_gif is not None:
            display_gif = show_gif
            user_settings["roll_gifs_disabled"] = not display_gif
            await self._save_json(self.settings_data, self.settings_file)
        else:
            display_gif = not disabled_gifs
        
        if display_gif:
            embed_url = self._get_random_embed_url(user_id, "roll")
            embed = discord.Embed(
                title=f"🎲 Rolled {dice}: Result is {total}",
                description=f"Individual rolls: `{'`, `'.join(map(str, rolls))}`" if num_dice > 1 else "",
                color=discord.Color.blue()
            )
            embed.set_image(url=embed_url)
        else:
            # text embed
            embed = discord.Embed(
                title=f"Dice Roll: {dice}",
                color=discord.Color.blue()
            )
            embed.add_field(name="Total", value=f"**` {total} `**", inline=True)
            if num_dice > 1:
                embed.add_field(name="Rolls", value=f"` {', '.join(map(str, rolls))} `", inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rps", description="Play Rock, Paper, Scissors against me.")
    @app_commands.describe(choice="Your choice.")
    @app_commands.choices(choice=[app_commands.Choice(name="Rock", value="rock"), app_commands.Choice(name="Paper", value="paper"), app_commands.Choice(name="Scissors", value="scissors"),])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def rps(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        user_choice, bot_choice = choice.value, random.choice(["rock", "paper", "scissors"])
        if user_choice == bot_choice:
            result_text, color = PERSONALITY["rps_tie"].format(user_choice=user_choice), discord.Color.light_gray()
        elif (user_choice, bot_choice) in [("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")]:
            result_text, color = PERSONALITY["rps_win"].format(user_choice=user_choice.title(), bot_choice=bot_choice), discord.Color.green()
        else:
            result_text, color = PERSONALITY["rps_lose"].format(user_choice=user_choice.title(), bot_choice=bot_choice), discord.Color.red()
        embed = discord.Embed(description=result_text, color=color)
        embed.set_image(url=self._get_random_embed_url(interaction.user.id, "rps"))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setgifsource", description="Choose which server's GIFs to use for fun commands.")
    @app_commands.describe(command="The command to set the GIF source for.")
    @app_commands.choices(command=[
        app_commands.Choice(name="Coinflip", value="coinflip"),
        app_commands.Choice(name="Roll", value="roll"),
        app_commands.Choice(name="RPS", value="rps"),
    ])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def setgifsource(self, interaction: discord.Interaction, command: app_commands.Choice[str]):
        command_name = command.value
        available_guilds = self._get_available_gif_guilds(command_name)
        
        if not available_guilds:
            return await interaction.response.send_message(PERSONALITY["no_gif_sources"], ephemeral=True)
        
        view = GifSourceView(self, interaction.user.id, command_name, available_guilds)
        await interaction.response.send_message(f"Choose the GIF source for **{command.name}** commands:", view=view, ephemeral=True)

    @app_commands.command(name="funembeds", description="Add a new image/GIF for a fun command.")
    @app_commands.describe(command="The command to add the image to.", url="The direct URL of the image or GIF.")
    @app_commands.choices(command=[app_commands.Choice(name="Coinflip", value="coinflip"), app_commands.Choice(name="Roll", value="roll"), app_commands.Choice(name="RPS", value="rps"),])
    @app_commands.allowed_installs(guilds=True, users=False)  # Only in guilds for adding GIFs
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
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