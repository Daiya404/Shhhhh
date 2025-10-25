# cogs/moderation/link_fixer.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import asyncio
from typing import Dict, Optional

from utils.websites import all_websites, Website
from config.personalities import PERSONALITY_RESPONSES

class LinkFixerView(discord.ui.View):
    def __init__(self, original_message_id: int, original_channel_id: int, original_author_id: int, source_url: str):
        super().__init__(timeout=None)
        self.original_message_id = original_message_id
        self.original_channel_id = original_channel_id
        self.original_author_id = original_author_id
        self.add_item(discord.ui.Button(label="Source", style=discord.ButtonStyle.link, url=source_url))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.original_author_id: return True
        await interaction.response.send_message("Hmph. This isn't your message to manage.", ephemeral=True)
        return False

    @discord.ui.button(label="Revert", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def revert_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        try:
            channel = interaction.client.get_channel(self.original_channel_id)
            if channel:
                original_message = await channel.fetch_message(self.original_message_id)
                await original_message.edit(suppress=False)
        except (discord.NotFound, discord.Forbidden): pass
        await interaction.response.send_message("Fine, I've reverted it.", ephemeral=True, delete_after=5)

class LinkFixer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["link_fixer"]
        self.data_manager = self.bot.data_manager

        self.settings_cache: Dict = {}
        self.website_map: Dict[str, Website] = {}
        self.combined_pattern: Optional[re.Pattern] = None
        
        self._is_dirty = asyncio.Event()
        self._save_lock = asyncio.Lock()
        self.save_task: Optional[asyncio.Task] = None

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        feature_manager = self.bot.get_cog("FeatureManager")
        feature_name = "link_fixer" 
        
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, feature_name):
            await interaction.response.send_message(f"Hmph. The {feature_name.replace('_', ' ').title()} feature is disabled on this server.", ephemeral=True)
            return False
        return True

    async def cog_load(self):
        self.logger.info("Loading link fixer settings and compiling pattern...")
        self.settings_cache = await self.data_manager.get_data("link_fixer_settings") or {}
        
        patterns = []
        for name, website_class in all_websites.items():
            patterns.append(f"(?P<{name}>{website_class.pattern.pattern})")
            self.website_map[name] = website_class
        
        if patterns:
            self.combined_pattern = re.compile("|".join(patterns), re.IGNORECASE)
        
        self.save_task = self.bot.loop.create_task(self._periodic_save())

    async def cog_unload(self):
        if self.save_task: self.save_task.cancel()
        if self._is_dirty.is_set():
            self.logger.info("Performing final save for link fixer settings...")
            await self.data_manager.save_data("link_fixer_settings", self.settings_cache)

    async def _periodic_save(self):
        while not self.bot.is_closed():
            try:
                await self._is_dirty.wait()
                await asyncio.sleep(60)
                async with self._save_lock:
                    await self.data_manager.save_data("link_fixer_settings", self.settings_cache)
                    self._is_dirty.clear()
            except asyncio.CancelledError: break
            except Exception as e:
                self.logger.error(f"Error in link fixer periodic save task: {e}", exc_info=True)
                await asyncio.sleep(120)

    async def check_and_fix_link(self, message: discord.Message) -> bool:
        if not message.guild or message.author.bot or not self.combined_pattern:
            return False

        content = message.content
        matches = list(self.combined_pattern.finditer(content))
        if not matches:
            return False

        for match in matches:
            match_start, match_end = match.start(), match.end()
            last_spoiler_before = content.rfind('||', 0, match_start)
            first_spoiler_after = content.find('||', match_end)

            is_spoiler = False
            if last_spoiler_before != -1 and first_spoiler_after != -1:
                if content.find('||', last_spoiler_before + 2, match_start) == -1:
                    is_spoiler = True

            asyncio.create_task(self.process_link_fix(message, match, is_spoiler))
        
        return True

    async def process_link_fix(self, message: discord.Message, match: re.Match, is_spoiler: bool):
        website_name = match.lastgroup
        if not website_name: return

        website_class = self.website_map.get(website_name)
        if not website_class: return
        
        user_settings = self.settings_cache.get(str(message.guild.id), {}).get("users", {}).get(str(message.author.id), {})
        if not user_settings.get(website_name, True):
            return

        try:
            await message.add_reaction("⏳")
        except (discord.Forbidden, discord.HTTPException):
            pass

        try:
            link_data = await website_class.get_links(match, session=self.bot.http_session)
            if not link_data: return

            response_content = self._format_response(link_data)

            if is_spoiler:
                response_content = f"||{response_content}||"

            view = LinkFixerView(
                original_message_id=message.id,
                original_channel_id=message.channel.id,
                original_author_id=message.author.id,
                source_url=link_data['original_url']
            )

            await message.reply(response_content, view=view, allowed_mentions=discord.AllowedMentions.none())
            if message.channel.permissions_for(message.guild.me).manage_messages:
                await message.edit(suppress=True)
                
        except Exception as e:
            self.logger.error(f"Failed to fix link for {website_name}: {e}", exc_info=True)
        finally:
            try:
                await message.remove_reaction("⏳", self.bot.user)
            except (discord.Forbidden, discord.HTTPException):
                pass
    
    def _format_response(self, link_data: Dict[str, str]) -> str:
        display_name = link_data.get('display_name', 'Link')
        fixed_url = link_data.get('fixed_url')
        
        if not fixed_url: return "Could not fix link."

        if author_name := link_data.get("author_name"):
            return f"[{display_name} by {author_name}]({fixed_url})"
        elif fixer_name := link_data.get("fixer_name"):
            return f"[{display_name}]({fixed_url}) • Fixed with *{fixer_name}*"
        else:
            return f"[{display_name}]({fixed_url})"

    @app_commands.command(name="linkfixer-settings", description="Enable or disable link fixing for yourself.")
    @app_commands.describe(website="The website you want to configure for yourself.", state="Whether to turn fixing 'On' or 'Off' for your links.")
    @app_commands.choices(website=[app_commands.Choice(name=name.title(), value=name) for name in sorted(all_websites.keys())], state=[app_commands.Choice(name="On", value="on"), app_commands.Choice(name="Off", value="off")])
    async def manage_linkfixer_settings(self, interaction: discord.Interaction, website: str, state: str):
        if not await self._is_feature_enabled(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild_id, user_id = str(interaction.guild.id), str(interaction.user.id)
        
        user_settings = self.settings_cache.setdefault(guild_id, {}).setdefault("users", {}).setdefault(user_id, {})
        new_state_bool = (state == "on")
        user_settings[website] = new_state_bool
        
        self._is_dirty.set()
        
        response_msg = self.personality['personal_opt_in'] if new_state_bool else self.personality['personal_opt_out']
        await interaction.followup.send(response_msg.replace("link fixing", f"**{website.title()}** link fixing"))

async def setup(bot):
    await bot.add_cog(LinkFixer(bot))