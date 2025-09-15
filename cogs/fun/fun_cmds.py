# cogs/fun/fun_cmds.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import random
import re
import asyncio
import aiohttp
from typing import Dict, List, Optional

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin
from utils.frustration_manager import get_frustration_level

# --- Helper Classes ---
# These helper views are efficient and do not require changes.
class GifSourceSelect(discord.ui.Select):
    def __init__(self, fun_cog, command: str, available_guilds: Dict[str, str]):
        self.fun_cog = fun_cog
        self.command = command
        options = [discord.SelectOption(label="Default GIFs", value="default", description="Use built-in default GIFs", emoji="🎲")]
        guild_options = [discord.SelectOption(label=guild_name[:100], value=guild_id, description=f"Use GIFs from {guild_name}"[:100], emoji="🏠") for guild_id, guild_name in list(available_guilds.items())[:24]]
        options.extend(guild_options)
        super().__init__(placeholder="Choose a GIF source...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_value = self.values[0]
        guild_id_str, user_id_str = str(interaction.guild.id), str(interaction.user.id)
        user_prefs = self.fun_cog.user_prefs_cache.setdefault(guild_id_str, {}).setdefault(user_id_str, {})
        
        if selected_value == "default":
            user_prefs.pop(self.command, None)
            response_msg = self.fun_cog.personality["gif_source_reset"].format(command=self.command)
        else:
            guild_name = self.view.available_guilds.get(selected_value, "Unknown Server")
            user_prefs[self.command] = selected_value
            response_msg = self.fun_cog.personality["gif_source_set"].format(guild_name=guild_name, command=self.command)
        
        self.fun_cog._is_dirty.set() # Signal that a save is needed
        await interaction.edit_original_response(content=response_msg, view=None)

class GifSourceView(discord.ui.View):
    def __init__(self, fun_cog, command: str, available_guilds: Dict[str, str], interaction_user_id: int):
        super().__init__(timeout=300)
        self.available_guilds = available_guilds
        self.interaction_user_id = interaction_user_id
        self.add_item(GifSourceSelect(fun_cog, command, available_guilds))
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.interaction_user_id: return True
        await interaction.response.send_message("This menu is not for you!", ephemeral=True)
        return False

# --- The Main Cog ---
class FunCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["fun_cmds"]
        self.data_manager = self.bot.data_manager
        
        # --- Caches ---
        self.embed_data_cache: Dict[str, Dict[str, List[str]]] = {}
        self.user_prefs_cache: Dict[str, Dict[str, Dict[str, str]]] = {}
        
        # --- OPTIMIZATIONS ---
        self._is_dirty = asyncio.Event()
        self.save_task = self.periodic_save.start()
        
        self.default_embeds = {
            "coinflip": ["https://media1.tenor.com/m/gT2UI5h7-4sAAAAC/coin-flip-heads.gif", "https://media1.tenor.com/m/8bNNw8QEk7wAAAAC/coin-flip.gif"],
            "roll": ["https://media1.tenor.com/m/Z2WSYMOa2oYAAAAC/dice-roll.gif", "https://media1.tenor.com/m/dK9g5qs7N8cAAAAC/rolling-dice.gif"],
            "rps": ["https://media1.tenor.com/m/y6gH0Q5i3iMAAAAC/rock-paper-scissors-anime.gif", "https://media1.tenor.com/m/nR7HqHE6ZBYAAAAC/rock-paper-scissors.gif"]
        }
        self.dice_pattern = re.compile(r'(\d+)d(\d+)(?:([+\-])(\d+))?', re.IGNORECASE)
        self.url_pattern = re.compile(r'^https?://(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|localhost|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::\d+)?(?:/?|[/?]\S+)$', re.IGNORECASE)

    async def cog_load(self):
        """Load fun command data into memory when the cog is loaded."""
        self.logger.info("Loading fun command data into memory...")
        self.embed_data_cache = await self.data_manager.get_data("fun_embeds")
        self.user_prefs_cache = await self.data_manager.get_data("user_gif_preferences")
        self.logger.info("Fun command data cache loaded successfully.")

    async def cog_unload(self):
        """Cancel tasks and perform a final save on shutdown."""
        self.save_task.cancel()
        if self._is_dirty.is_set():
            self.logger.info("Performing final save for fun_cmds data...")
            await self._save_all_data()

    @tasks.loop(minutes=5)
    async def periodic_save(self):
        """Background task to save caches to disk if they have changed."""
        await self._is_dirty.wait()
        await self._save_all_data()
        self._is_dirty.clear()
        self.logger.info("Periodically saved fun_cmds data.")

    async def _save_all_data(self):
        """A single function to save all data caches for this cog."""
        await self.data_manager.save_data("fun_embeds", self.embed_data_cache)
        await self.data_manager.save_data("user_gif_preferences", self.user_prefs_cache)

    async def _validate_url(self, url: str) -> bool:
        if not self.url_pattern.match(url): return False
        try:
            async with self.bot.http_session.head(url, timeout=10) as response:
                return response.status == 200 and response.content_type.startswith(('image/', 'video/'))
        except Exception: return False

    def _get_random_embed_url(self, interaction: discord.Interaction, command: str) -> str:
        guild_id, user_id = str(interaction.guild.id), str(interaction.user.id)
        prefs = self.user_prefs_cache.get(guild_id, {}).get(user_id, {})
        if pref_guild_id := prefs.get(command):
            if urls := self.embed_data_cache.get(pref_guild_id, {}).get(command, []): return random.choice(urls)
        if guild_urls := self.embed_data_cache.get(guild_id, {}).get(command, []): return random.choice(guild_urls)
        return random.choice(self.default_embeds.get(command, [""]))

    @app_commands.command(name="coinflip", description="Flip a coin and see if you get heads or tails!")
    async def coinflip(self, interaction: discord.Interaction):
        flipping_url = self._get_random_embed_url(interaction, "coinflip")
        embed = discord.Embed(title="🪙 Flipping coin...", color=discord.Color.gold(), description="*The coin spins...*")
        if flipping_url: embed.set_image(url=flipping_url)
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(random.uniform(2, 4))
        
        frustration = get_frustration_level(self.bot, interaction)
        response_index = min(frustration, len(self.personality["coinflip_responses"]) - 1)
        result = random.choice(["Heads", "Tails"])
        response_template = self.personality["coinflip_responses"][response_index]
        result_embed = discord.Embed(
            title=f"{'👑' if result == 'Heads' else '🔹'} Coin Flip Result: {result}!",
            description=response_template.format(result=result),
            color=discord.Color.green() if result == "Heads" else discord.Color.red()
        )
        if flipping_url: result_embed.set_image(url=flipping_url)
        await interaction.edit_original_response(embed=result_embed)

    @app_commands.command(name="roll", description="Roll dice in XdY format (e.g., 1d6, 2d20, 3d6+5).")
    @app_commands.describe(dice="The dice to roll (e.g., 1d6, 2d20, 1d20+5)")
    async def roll(self, interaction: discord.Interaction, dice: str):
        match = self.dice_pattern.match(dice.lower().strip())
        if not match: return await interaction.response.send_message("❌ Invalid dice format!", ephemeral=True)
        num_dice, num_sides = int(match.group(1)), int(match.group(2))
        modifier = int(match.group(4)) * (1 if match.group(3) == '+' else -1) if match.group(3) else 0
        if not (1 <= num_dice <= 100 and 2 <= num_sides <= 1000 and abs(modifier) <= 1000):
            return await interaction.response.send_message("❌ Dice or modifier amount is out of bounds.", ephemeral=True)
        rolls = [random.randint(1, num_sides) for _ in range(num_dice)]; final_total = sum(rolls) + modifier
        embed = discord.Embed(title=f"🎲 Rolled {dice.upper()}: **{final_total}**", color=discord.Color.blue())
        if embed_url := self._get_random_embed_url(interaction, "roll"): embed.set_image(url=embed_url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rps", description="Play Rock, Paper, Scissors against the bot!")
    @app_commands.describe(choice="Choose your weapon!")
    @app_commands.choices(choice=[app_commands.Choice(name="🗿 Rock", value="rock"), app_commands.Choice(name="📄 Paper", value="paper"), app_commands.Choice(name="✂️ Scissors", value="scissors")])
    async def rps(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        user_choice = choice.value; bot_choice = random.choice(["rock", "paper", "scissors"])
        if user_choice == bot_choice: result_key, color = "rps_tie", discord.Color.light_gray()
        elif (user_choice, bot_choice) in [("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")]: result_key, color = "rps_win", discord.Color.green()
        else: result_key, color = "rps_lose", discord.Color.red()
        result_text = self.personality[result_key].format(user_choice=user_choice.title(), bot_choice=bot_choice.title())
        embed = discord.Embed(title=f"Rock, Paper, Scissors!", description=result_text, color=color)
        if embed_url := self._get_random_embed_url(interaction, "rps"): embed.set_image(url=embed_url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="fun-admin", description="[Admin] Manage custom GIFs for fun commands.")
    # --- FIX: Stacked decorators on separate lines ---
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(action="What to do", command="The command to modify", url="The GIF URL")
    @app_commands.choices(action=[app_commands.Choice(name="Add GIF", value="add"), app_commands.Choice(name="List GIFs", value="list"), app_commands.Choice(name="Remove GIF", value="remove"), app_commands.Choice(name="Clear All", value="clear")], command=[app_commands.Choice(name="Coinflip", value="coinflip"), app_commands.Choice(name="Roll", value="roll"), app_commands.Choice(name="RPS", value="rps")])
    async def fun_admin(self, interaction: discord.Interaction, action: app_commands.Choice[str], command: app_commands.Choice[str], url: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        guild_id, cmd_name = str(interaction.guild.id), command.value
        command_urls = self.embed_data_cache.setdefault(guild_id, {}).setdefault(cmd_name, [])
        
        if action.value == "add":
            if not url: return await interaction.followup.send("❌ URL is required.")
            if not await self._validate_url(url): return await interaction.followup.send("❌ Invalid or inaccessible URL.")
            if url in command_urls: return await interaction.followup.send("❌ This URL is already added.")
            command_urls.append(url)
            self._is_dirty.set()
            await interaction.followup.send(f"✅ Added GIF to **{command.name}**.")
        elif action.value == "list":
            if not command_urls: return await interaction.followup.send(f"No custom GIFs for **{command.name}**.")
            embed = discord.Embed(title=f"🖼️ {command.name} GIFs", description="\n".join([f"• [Link {i+1}]({u})" for i, u in enumerate(command_urls[:10])]))
            await interaction.followup.send(embed=embed)
        elif action.value == "remove":
            if not url: return await interaction.followup.send("❌ URL is required.")
            if url not in command_urls: return await interaction.followup.send("❌ URL not found.")
            command_urls.remove(url)
            self._is_dirty.set()
            await interaction.followup.send(f"✅ Removed GIF from **{command.name}**.")
        elif action.value == "clear":
            if not command_urls: return await interaction.followup.send(f"No GIFs to clear for **{command.name}**.")
            command_urls.clear()
            self._is_dirty.set()
            await interaction.followup.send(f"✅ Cleared all GIFs from **{command.name}**.")

    @app_commands.command(name="fun-embeds-selection", description="Choose which server's GIFs to use for fun commands.")
    @app_commands.describe(command="The command to set the GIF source for")
    @app_commands.choices(command=[app_commands.Choice(name="Coinflip", value="coinflip"), app_commands.Choice(name="Roll", value="roll"), app_commands.Choice(name="RPS", value="rps")])
    async def fun_embeds_selection(self, interaction: discord.Interaction, command: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        command_name = command.value
        available_guilds = {gid: self.bot.get_guild(int(gid)).name for gid, cdata in self.embed_data_cache.items() if command_name in cdata and cdata[command_name] and self.bot.get_guild(int(gid))}
        if not available_guilds: return await interaction.followup.send(f"❌ No other servers have custom GIFs for **{command.name}**.")
        view = GifSourceView(self, command_name, available_guilds, interaction.user.id)
        await interaction.followup.send(f"🎨 Choose the GIF source for your **{command.name}** commands:", view=view)

async def setup(bot):
    await bot.add_cog(FunCommands(bot))