# cogs/fun/fun_cmds.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import random
import re
import asyncio
import aiohttp
from typing import Dict, List, Optional, Union
from urllib.parse import urlparse

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin
from utils.frustration_manager import get_frustration_level

# --- Helper Classes for GIF Source Selection ---

class GifSourceSelect(discord.ui.Select):
    def __init__(self, fun_cog, command: str, available_guilds: Dict[str, str]):
        self.fun_cog = fun_cog
        self.command = command
        
        options = [
            discord.SelectOption(
                label="Default GIFs", 
                value="default", 
                description="Use built-in default GIFs", 
                emoji="🎲"
            )
        ]
        
        # Add guilds that have GIFs for this specific command (limit to 24)
        guild_options = [
            discord.SelectOption(
                label=guild_name[:100], 
                value=guild_id, 
                description=f"Use GIFs from {guild_name}"[:100], 
                emoji="🏠"
            )
            for guild_id, guild_name in list(available_guilds.items())[:24]
        ]
        options.extend(guild_options)
        
        super().__init__(
            placeholder="Choose a GIF source...", 
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_value = self.values[0]
        
        # Get user preferences
        guild_id_str = str(interaction.guild_id)
        user_id_str = str(interaction.user.id)
        user_prefs = self.fun_cog.user_prefs_cache.setdefault(guild_id_str, {}).setdefault(user_id_str, {})
        
        if selected_value == "default":
            user_prefs.pop(self.command, None)
            response_msg = self.fun_cog.personality["gif_source_reset"].format(command=self.command)
        else:
            guild_name = self.view.available_guilds.get(selected_value, "Unknown Server")
            user_prefs[self.command] = selected_value
            response_msg = self.fun_cog.personality["gif_source_set"].format(
                guild_name=guild_name, 
                command=self.command
            )
        
        # Save preferences
        await self.fun_cog.data_manager.save_data("user_gif_preferences", self.fun_cog.user_prefs_cache)
        
        # Update message
        await interaction.edit_original_response(content=response_msg, view=None)

class GifSourceView(discord.ui.View):
    def __init__(self, fun_cog, command: str, available_guilds: Dict[str, str], interaction_user_id: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.available_guilds = available_guilds
        self.interaction_user_id = interaction_user_id
        self.add_item(GifSourceSelect(fun_cog, command, available_guilds))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.interaction_user_id:
            return True
        await interaction.response.send_message(
            "This menu is not for you! Use `/fun-embeds-selection` to create your own.", 
            ephemeral=True
        )
        return False

    async def on_timeout(self):
        # Disable all components when view times out
        for item in self.children:
            item.disabled = True

# --- The Main Cog ---

class FunCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["fun_cmds"]
        self.data_manager = self.bot.data_manager
        
        # Caches
        self.embed_data_cache: Dict[str, Dict[str, List[str]]] = {}
        self.user_prefs_cache: Dict[str, Dict[str, Dict[str, str]]] = {}
        self.command_stats_cache: Dict[str, Dict[str, int]] = {}
        
        # Enhanced default embeds with multiple options
        self.default_embeds = {
            "coinflip": [
                "https://media1.tenor.com/m/gT2UI5h7-4sAAAAC/coin-flip-heads.gif",
                "https://media1.tenor.com/m/8bNNw8QEk7wAAAAC/coin-flip.gif",
                "https://media1.tenor.com/m/YjzC0yBgQ7UAAAAC/flipping-coin.gif"
            ],
            "roll": [
                "https://media1.tenor.com/m/Z2WSYMOa2oYAAAAC/dice-roll.gif",
                "https://media1.tenor.com/m/dK9g5qs7N8cAAAAC/rolling-dice.gif",
                "https://media1.tenor.com/m/7wKxQpGAKFAAAAAC/dice.gif"
            ],
            "rps": [
                "https://media1.tenor.com/m/y6gH0Q5i3iMAAAAC/rock-paper-scissors-anime.gif",
                "https://media1.tenor.com/m/nR7HqHE6ZBYAAAAC/rock-paper-scissors.gif"
            ]
        }
        
        # Enhanced dice pattern to support modifiers
        self.dice_pattern = re.compile(r'(\d+)d(\d+)(?:([+\-])(\d+))?', re.IGNORECASE)
        
        # URL validation pattern
        self.url_pattern = re.compile(
            r'^https?://'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
            r'localhost|'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'
            r'(?:/?|[/?]\S+)$', re.IGNORECASE
        )

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """A local check to see if the fun_commands feature is enabled."""
        feature_manager = self.bot.get_cog("FeatureManager")
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, "fun_commands"):
            await interaction.response.send_message("Hmph. The Custom Roles feature is disabled on this server.", ephemeral=True)
            return False
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        """Load all fun data into memory when the cog is ready."""
        self.logger.info("Loading fun command data into memory...")
        try:
            self.embed_data_cache = await self.data_manager.get_data("fun_embeds")
            self.user_prefs_cache = await self.data_manager.get_data("user_gif_preferences")
            self.command_stats_cache = await self.data_manager.get_data("fun_command_stats")
            self.logger.info("Fun command data cache loaded successfully.")
        except Exception as e:
            self.logger.error(f"Failed to load fun command data: {e}")
            # Initialize empty caches on failure
            self.embed_data_cache = {}
            self.user_prefs_cache = {}
            self.command_stats_cache = {}

    async def _validate_url(self, url: str) -> bool:
        """Validate URL format and check if it's accessible."""
        if not self.url_pattern.match(url):
            return False
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.head(url) as response:
                    return response.status == 200 and response.content_type.startswith(('image/', 'video/'))
        except Exception:
            return False

    def _get_random_embed_url(self, interaction: discord.Interaction, command: str) -> str:
        """Get a random embed URL based on user preferences, with fallback logic."""
        try:
            guild_id_str = str(interaction.guild_id)
            user_id_str = str(interaction.user.id)
            
            # Check user preferences first
            user_prefs = self.user_prefs_cache.get(guild_id_str, {}).get(user_id_str, {})
            preferred_guild_id = user_prefs.get(command)
            
            if preferred_guild_id:
                urls = self.embed_data_cache.get(preferred_guild_id, {}).get(command, [])
                if urls:
                    return random.choice(urls)
            
            # Fall back to current guild's GIFs
            guild_urls = self.embed_data_cache.get(guild_id_str, {}).get(command, [])
            if guild_urls:
                return random.choice(guild_urls)
            
            # Final fallback to defaults
            default_urls = self.default_embeds.get(command, [""])
            return random.choice(default_urls)
            
        except Exception as e:
            self.logger.error(f"Error getting embed URL for {command}: {e}")
            return random.choice(self.default_embeds.get(command, [""]))

    async def _increment_command_stat(self, guild_id: int, command: str):
        """Track command usage statistics."""
        try:
            guild_stats = self.command_stats_cache.setdefault(str(guild_id), {})
            guild_stats[command] = guild_stats.get(command, 0) + 1
            await self.data_manager.save_data("fun_command_stats", self.command_stats_cache)
        except Exception as e:
            self.logger.error(f"Failed to increment command stat: {e}")

    @app_commands.command(name="coinflip", description="Flip a coin and see if you get heads or tails!")
    async def coinflip(self, interaction: discord.Interaction):
        if not await self._is_feature_enabled(interaction): return
        await self._increment_command_stat(interaction.guild_id, "coinflip")
        
        flipping_url = self._get_random_embed_url(interaction, "coinflip")
        embed = discord.Embed(
            title="🪙 Flipping coin...", 
            color=discord.Color.gold(),
            description="*The coin spins through the air...*"
        )
        if flipping_url:
            embed.set_image(url=flipping_url)
        
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(random.uniform(2, 4))  # Variable delay for suspense
        
        # Get frustration level for response variety
        frustration = get_frustration_level(self.bot, interaction)
        response_index = min(frustration, len(self.personality["coinflip_responses"]) - 1)
        
        result = random.choice(["Heads", "Tails"])
        response_template = self.personality["coinflip_responses"][response_index]
        color = discord.Color.green() if result == "Heads" else discord.Color.red()
        emoji = "👑" if result == "Heads" else "🔹"
        
        result_embed = discord.Embed(
            title=f"{emoji} Coin Flip Result: {result}!",
            description=response_template.format(result=result),
            color=color
        )
        if flipping_url:
            result_embed.set_image(url=flipping_url)
        
        await interaction.edit_original_response(embed=result_embed)

    @app_commands.command(name="roll", description="Roll dice in XdY format (e.g., 1d6, 2d20, 3d6+5).")
    @app_commands.describe(dice="The dice to roll (e.g., 1d6, 2d20, 1d20+5)")
    async def roll(self, interaction: discord.Interaction, dice: str):
        if not await self._is_feature_enabled(interaction): return
        await self._increment_command_stat(interaction.guild_id, "roll")
        
        # Enhanced dice parsing with modifiers
        match = self.dice_pattern.match(dice.lower().strip())
        if not match:
            return await interaction.response.send_message(
                "❌ Invalid dice format! Use formats like: `1d6`, `2d20`, `3d6+5`, `1d8-2`", 
                ephemeral=True
            )

        num_dice, num_sides = int(match.group(1)), int(match.group(2))
        modifier = 0
        if match.group(3) and match.group(4):
            modifier = int(match.group(4)) * (1 if match.group(3) == '+' else -1)

        # Validation
        if not (1 <= num_dice <= 100):
            return await interaction.response.send_message("❌ You can roll 1-100 dice at once.", ephemeral=True)
        if not (2 <= num_sides <= 1000):
            return await interaction.response.send_message("❌ Dice must have between 2-1000 sides.", ephemeral=True)
        if abs(modifier) > 1000:
            return await interaction.response.send_message("❌ Modifier must be between -1000 and +1000.", ephemeral=True)

        # Roll the dice
        rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
        base_total = sum(rolls)
        final_total = base_total + modifier
        
        embed_url = self._get_random_embed_url(interaction, "roll")
        
        # Create result description
        description_parts = []
        if num_dice <= 20:  # Only show individual rolls for reasonable amounts
            description_parts.append(f"**Rolls:** {', '.join(map(str, rolls))}")
        
        if modifier != 0:
            modifier_str = f"+{modifier}" if modifier > 0 else str(modifier)
            description_parts.append(f"**Base Total:** {base_total}")
            description_parts.append(f"**Modifier:** {modifier_str}")
            description_parts.append(f"**Final Total:** {final_total}")
        
        embed = discord.Embed(
            title=f"🎲 Rolled {dice.upper()}: **{final_total}**",
            description="\n".join(description_parts) if description_parts else "",
            color=discord.Color.blue()
        )
        
        if embed_url:
            embed.set_image(url=embed_url)
        
        # Add some flavor based on results
        if num_dice == 1:
            if rolls[0] == 1:
                embed.add_field(name="💀", value="Critical Failure!", inline=False)
            elif rolls[0] == num_sides:
                embed.add_field(name="✨", value="Critical Success!", inline=False)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rps", description="Play Rock, Paper, Scissors against the bot!")
    @app_commands.describe(choice="Choose your weapon!")
    @app_commands.choices(choice=[
        app_commands.Choice(name="🗿 Rock", value="rock"),
        app_commands.Choice(name="📄 Paper", value="paper"),
        app_commands.Choice(name="✂️ Scissors", value="scissors")
    ])
    async def rps(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        if not await self._is_feature_enabled(interaction): return
        await self._increment_command_stat(interaction.guild_id, "rps")
        
        user_choice = choice.value
        bot_choice = random.choice(["rock", "paper", "scissors"])
        
        # Determine result
        if user_choice == bot_choice:
            result_text = self.personality["rps_tie"].format(user_choice=user_choice.title())
            color = discord.Color.light_gray()
            emoji = "🤝"
        elif (user_choice, bot_choice) in [("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")]:
            result_text = self.personality["rps_win"].format(
                user_choice=user_choice.title(), 
                bot_choice=bot_choice.title()
            )
            color = discord.Color.green()
            emoji = "🎉"
        else:
            result_text = self.personality["rps_lose"].format(
                user_choice=user_choice.title(), 
                bot_choice=bot_choice.title()
            )
            color = discord.Color.red()
            emoji = "😔"

        embed = discord.Embed(
            title=f"{emoji} Rock, Paper, Scissors Result!",
            description=result_text,
            color=color
        )
        
        # Add choice visualization
        choice_emojis = {"rock": "🗿", "paper": "📄", "scissors": "✂️"}
        embed.add_field(
            name="Choices",
            value=f"You: {choice_emojis[user_choice]} {user_choice.title()}\nBot: {choice_emojis[bot_choice]} {bot_choice.title()}",
            inline=False
        )
        
        embed_url = self._get_random_embed_url(interaction, "rps")
        if embed_url:
            embed.set_image(url=embed_url)
        
        await interaction.response.send_message(embed=embed)

    # --- Admin & Settings Commands ---
    
    @app_commands.command(name="fun-admin", description="[Admin] Manage custom GIFs for fun commands.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        action="What to do with the GIF",
        command="The command to modify",
        url="The direct URL of the image/GIF (for add action)"
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Add GIF", value="add"),
            app_commands.Choice(name="List GIFs", value="list"),
            app_commands.Choice(name="Remove GIF", value="remove"),
            app_commands.Choice(name="Clear All", value="clear")
        ],
        command=[
            app_commands.Choice(name="Coinflip", value="coinflip"),
            app_commands.Choice(name="Roll", value="roll"),
            app_commands.Choice(name="RPS", value="rps")
        ]
    )
    async def fun_admin(self, interaction: discord.Interaction, action: app_commands.Choice[str], 
                       command: app_commands.Choice[str], url: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        
        guild_id = str(interaction.guild_id)
        command_name = command.value
        action_name = action.value
        
        guild_embeds = self.embed_data_cache.setdefault(guild_id, {})
        command_urls = guild_embeds.setdefault(command_name, [])
        
        if action_name == "add":
            if not url:
                return await interaction.followup.send("❌ URL is required for adding GIFs.")
            
            if not await self._validate_url(url):
                return await interaction.followup.send("❌ Invalid URL or URL not accessible. Please provide a direct link to an image/GIF.")
            
            if url in command_urls:
                return await interaction.followup.send("❌ This URL is already added for this command.")
            
            command_urls.append(url)
            await self.data_manager.save_data("fun_embeds", self.embed_data_cache)
            await interaction.followup.send(
                f"✅ Added GIF to **{command.name}** command! ({len(command_urls)} total GIFs)"
            )
            
        elif action_name == "list":
            if not command_urls:
                return await interaction.followup.send(f"No custom GIFs configured for **{command.name}**.")
            
            embed = discord.Embed(
                title=f"🖼️ {command.name} GIFs ({len(command_urls)})",
                color=discord.Color.blue()
            )
            
            for i, gif_url in enumerate(command_urls[:10], 1):  # Show first 10
                embed.add_field(
                    name=f"GIF #{i}",
                    value=f"[View GIF]({gif_url})",
                    inline=True
                )
            
            if len(command_urls) > 10:
                embed.set_footer(text=f"... and {len(command_urls) - 10} more")
            
            await interaction.followup.send(embed=embed)
            
        elif action_name == "remove":
            if not url:
                return await interaction.followup.send("❌ URL is required for removing GIFs.")
            
            if url not in command_urls:
                return await interaction.followup.send("❌ This URL is not found in the GIF list.")
            
            command_urls.remove(url)
            await self.data_manager.save_data("fun_embeds", self.embed_data_cache)
            await interaction.followup.send(
                f"✅ Removed GIF from **{command.name}** command! ({len(command_urls)} remaining)"
            )
            
        elif action_name == "clear":
            if not command_urls:
                return await interaction.followup.send(f"No GIFs to clear for **{command.name}**.")
            
            count = len(command_urls)
            command_urls.clear()
            await self.data_manager.save_data("fun_embeds", self.embed_data_cache)
            await interaction.followup.send(f"✅ Cleared {count} GIF{'s' if count != 1 else ''} from **{command.name}** command.")

    @app_commands.command(name="fun-embeds-selection", description="Choose which server's GIFs to use for fun commands.")
    @app_commands.describe(command="The command to set the GIF source for")
    @app_commands.choices(command=[
        app_commands.Choice(name="Coinflip", value="coinflip"),
        app_commands.Choice(name="Roll", value="roll"),
        app_commands.Choice(name="RPS", value="rps")
    ])
    async def fun_embeds_selection(self, interaction: discord.Interaction, command: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        command_name = command.value
        
        # Find all guilds with GIFs for this command
        available_guilds = {}
        for guild_id, commands_data in self.embed_data_cache.items():
            if command_name in commands_data and commands_data[command_name]:
                if guild := self.bot.get_guild(int(guild_id)):
                    available_guilds[guild_id] = guild.name
        
        if not available_guilds:
            return await interaction.followup.send(
                f"❌ No servers have custom GIFs configured for **{command.name}**.\n"
                "Ask your server admins to add some with `/fun-admin`!"
            )
        
        view = GifSourceView(self, command_name, available_guilds, interaction.user.id)
        await interaction.followup.send(
            f"🎨 Choose the GIF source for your **{command.name}** commands:",
            view=view
        )

async def setup(bot):
    await bot.add_cog(FunCommands(bot))