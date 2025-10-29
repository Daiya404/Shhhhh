# cogs/moderation/link_fixer.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import asyncio
from typing import Dict, Optional, Set
from collections import defaultdict

from utils.websites import all_websites, Website
from config.personalities import PERSONALITY_RESPONSES

class LinkFixerView(discord.ui.View):
    """Interactive view for fixed links with revert functionality."""
    
    def __init__(self, original_message_id: int, original_channel_id: int, 
                 original_author_id: int, source_url: str):
        super().__init__(timeout=None)
        self.original_message_id = original_message_id
        self.original_channel_id = original_channel_id
        self.original_author_id = original_author_id
        self.add_item(discord.ui.Button(
            label="Source", 
            style=discord.ButtonStyle.link, 
            url=source_url
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the original message author can interact."""
        if interaction.user.id == self.original_author_id:
            return True
        await interaction.response.send_message(
            "Hmph. This isn't your message to manage.", 
            ephemeral=True
        )
        return False

    @discord.ui.button(label="Revert", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def revert_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Revert the link fix by restoring the original message."""
        try:
            await interaction.message.delete()
        except discord.HTTPException as e:
            self.logger.warning(f"Failed to delete fixed message: {e}")
        
        try:
            channel = interaction.client.get_channel(self.original_channel_id)
            if channel:
                original_message = await channel.fetch_message(self.original_message_id)
                await original_message.edit(suppress=False)
                await interaction.response.send_message(
                    "Fine, I've reverted it.", 
                    ephemeral=True, 
                    delete_after=5
                )
            else:
                await interaction.response.send_message(
                    "Could not find the original channel.", 
                    ephemeral=True
                )
        except discord.NotFound:
            await interaction.response.send_message(
                "The original message was deleted.", 
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to unsuppress the message.", 
                ephemeral=True
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"An error occurred: {str(e)}", 
                ephemeral=True
            )

class LinkFixer(commands.Cog):
    """Automatically fixes social media links for better embedding."""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["link_fixer"]
        self.data_manager = self.bot.data_manager

        # Caching and pattern compilation
        self.settings_cache: Dict = {}
        self.website_map: Dict[str, Website] = {}
        self.combined_pattern: Optional[re.Pattern] = None
        
        # Persistent save system
        self._is_dirty = asyncio.Event()
        self._save_lock = asyncio.Lock()
        self.save_task: Optional[asyncio.Task] = None
        
        # Rate limiting per message to prevent abuse
        self._processing_messages: Set[int] = set()

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """Check if the link fixer feature is enabled for this guild."""
        feature_manager = self.bot.get_cog("FeatureManager")
        feature_name = "link_fixer"
        
        if not feature_manager or not feature_manager.is_feature_enabled(
            interaction.guild_id, feature_name
        ):
            await interaction.response.send_message(
                f"Hmph. The {feature_name.replace('_', ' ').title()} feature is disabled on this server.",
                ephemeral=True
            )
            return False
        return True

    async def cog_load(self):
        """Initialize settings, compile patterns, and start background tasks."""
        self.logger.info("Loading link fixer settings and compiling pattern...")
        
        # Load cached settings
        self.settings_cache = await self.data_manager.get_data("link_fixer_settings") or {}
        
        # Build combined regex pattern for all websites
        patterns = []
        for name, website_class in all_websites.items():
            patterns.append(f"(?P<{name}>{website_class.pattern.pattern})")
            self.website_map[name] = website_class
        
        if patterns:
            self.combined_pattern = re.compile("|".join(patterns), re.IGNORECASE)
            self.logger.info(f"Compiled pattern for {len(patterns)} websites")
        else:
            self.logger.warning("No website patterns available")
        
        # Start periodic save task
        self.save_task = self.bot.loop.create_task(self._periodic_save())

    async def cog_unload(self):
        """Clean up tasks and perform final save."""
        if self.save_task:
            self.save_task.cancel()
            try:
                await self.save_task
            except asyncio.CancelledError:
                pass
        
        if self._is_dirty.is_set():
            self.logger.info("Performing final save for link fixer settings...")
            async with self._save_lock:
                await self.data_manager.save_data("link_fixer_settings", self.settings_cache)

    async def _periodic_save(self):
        """Background task to periodically save settings."""
        while not self.bot.is_closed():
            try:
                await self._is_dirty.wait()
                await asyncio.sleep(60)  # Wait 60 seconds after changes
                
                async with self._save_lock:
                    await self.data_manager.save_data("link_fixer_settings", self.settings_cache)
                    self._is_dirty.clear()
                    self.logger.debug("Saved link fixer settings")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in link fixer periodic save task: {e}", exc_info=True)
                await asyncio.sleep(120)  # Wait longer after error

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for messages containing fixable links."""
        await self.check_and_fix_link(message)

    async def check_and_fix_link(self, message: discord.Message) -> bool:
        """Check if a message contains fixable links and process them."""
        # Basic validation
        if not message.guild or message.author.bot or not self.combined_pattern:
            return False
        
        # Prevent duplicate processing
        if message.id in self._processing_messages:
            return False

        content = message.content
        
        # First check if entire message is in spoiler
        is_spoiler = content.strip().startswith('||') and content.strip().endswith('||')
        
        # Remove markdown link syntax [text](url) to get plain URLs for matching
        plain_content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\2', content)
        
        matches = list(self.combined_pattern.finditer(plain_content))
        if not matches:
            return False

        self._processing_messages.add(message.id)
        
        try:
            for match in matches:
                self.logger.info(f"Processing link: {match.group(0)[:50]}... | Spoiler: {is_spoiler}")
                asyncio.create_task(self._process_link_fix_safe(message, match, is_spoiler))
        finally:
            # Clean up after a delay to prevent immediate re-processing
            asyncio.create_task(self._cleanup_processing_id(message.id))
        
        return True

    async def _cleanup_processing_id(self, message_id: int):
        """Remove message ID from processing set after a delay."""
        await asyncio.sleep(5)
        self._processing_messages.discard(message_id)

    async def _process_link_fix_safe(self, message: discord.Message, 
                                     match: re.Match, is_spoiler: bool):
        """Wrapper for process_link_fix with error handling."""
        try:
            await self.process_link_fix(message, match, is_spoiler)
        except Exception as e:
            self.logger.error(
                f"Unhandled error in link fix processing: {e}", 
                exc_info=True
            )

    async def process_link_fix(self, message: discord.Message, 
                              match: re.Match, is_spoiler: bool):
        """Process and fix a single link match."""
        website_name = match.lastgroup
        if not website_name:
            return

        website_class = self.website_map.get(website_name)
        if not website_class:
            return
        
        # Check user preferences
        user_settings = (
            self.settings_cache
            .get(str(message.guild.id), {})
            .get("users", {})
            .get(str(message.author.id), {})
        )
        
        if not user_settings.get(website_name, True):
            self.logger.debug(
                f"User {message.author.id} has disabled {website_name} fixing"
            )
            return

        # Add processing reaction
        try:
            await message.add_reaction("⏳")
        except (discord.Forbidden, discord.HTTPException) as e:
            self.logger.debug(f"Could not add reaction: {e}")

        try:
            # Get fixed link data
            link_data = await asyncio.wait_for(
                website_class.get_links(match, session=self.bot.http_session),
                timeout=10.0  # 10 second timeout
            )
            
            if not link_data:
                return

            response_content = self._format_response(link_data)

            # Apply spoiler tags to the entire response if needed
            if is_spoiler:
                response_content = f"|| {response_content} ||"

            view = LinkFixerView(
                original_message_id=message.id,
                original_channel_id=message.channel.id,
                original_author_id=message.author.id,
                source_url=link_data['original_url']
            )

            # Send fixed link
            await message.reply(
                response_content, 
                view=view, 
                allowed_mentions=discord.AllowedMentions.none(),
                suppress_embeds=False
            )
            
            # Suppress original embed if we have permission
            if message.channel.permissions_for(message.guild.me).manage_messages:
                try:
                    await message.edit(suppress=True)
                except discord.HTTPException as e:
                    self.logger.debug(f"Could not suppress original message: {e}")
                
        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout while fixing {website_name} link")
        except Exception as e:
            self.logger.error(
                f"Failed to fix link for {website_name}: {e}", 
                exc_info=True
            )
        finally:
            # Remove processing reaction
            try:
                await message.remove_reaction("⏳", self.bot.user)
            except (discord.Forbidden, discord.HTTPException) as e:
                self.logger.debug(f"Could not remove reaction: {e}")
    
    def _format_response(self, link_data: Dict[str, str]) -> str:
        """Format the response message with the fixed link."""
        display_name = link_data.get('display_name', 'Link')
        fixed_url = link_data.get('fixed_url')
        
        if not fixed_url:
            return "Could not fix link."

        # Prioritize author name, then fixer name, then plain link
        if author_name := link_data.get("author_name"):
            return f"[{display_name} by {author_name}]({fixed_url})"
        elif fixer_name := link_data.get("fixer_name"):
            return f"[{display_name}]({fixed_url}) • Fixed with *{fixer_name}*"
        else:
            return f"[{display_name}]({fixed_url})"

    @app_commands.command(
        name="linkfixer-settings",
        description="Enable or disable link fixing for specific websites."
    )
    @app_commands.describe(
        website="The website you want to configure for yourself.",
        state="Whether to turn fixing 'On' or 'Off' for your links."
    )
    @app_commands.choices(
        website=[
            app_commands.Choice(name=name.title(), value=name) 
            for name in sorted(all_websites.keys())
        ],
        state=[
            app_commands.Choice(name="On", value="on"),
            app_commands.Choice(name="Off", value="off")
        ]
    )
    async def manage_linkfixer_settings(
        self, 
        interaction: discord.Interaction, 
        website: str, 
        state: str
    ):
        """User command to manage their personal link fixer preferences."""
        if not await self._is_feature_enabled(interaction):
            return
            
        await interaction.response.defer(ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        # Ensure nested structure exists
        if guild_id not in self.settings_cache:
            self.settings_cache[guild_id] = {"users": {}}
        if "users" not in self.settings_cache[guild_id]:
            self.settings_cache[guild_id]["users"] = {}
        if user_id not in self.settings_cache[guild_id]["users"]:
            self.settings_cache[guild_id]["users"][user_id] = {}
        
        user_settings = self.settings_cache[guild_id]["users"][user_id]
        new_state_bool = (state == "on")
        user_settings[website] = new_state_bool
        
        # Mark as dirty for periodic save
        self._is_dirty.set()
        
        # Send confirmation
        response_msg = (
            self.personality['personal_opt_in'] 
            if new_state_bool 
            else self.personality['personal_opt_out']
        )
        await interaction.followup.send(
            response_msg.replace("link fixing", f"**{website.title()}** link fixing")
        )

async def setup(bot):
    await bot.add_cog(LinkFixer(bot))