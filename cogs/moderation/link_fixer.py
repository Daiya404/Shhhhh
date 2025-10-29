# cogs/moderation/link_fixer.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import asyncio
from typing import Dict, Optional, Set

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
        # Delete the bot's fixed message
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass
        
        # Restore the original message
        try:
            channel = interaction.client.get_channel(self.original_channel_id)
            if not channel:
                await interaction.response.send_message(
                    "Could not find the original channel.", 
                    ephemeral=True
                )
                return
                
            original_message = await channel.fetch_message(self.original_message_id)
            await original_message.edit(suppress=False)
            await interaction.response.send_message(
                "Fine, I've reverted it.", 
                ephemeral=True, 
                delete_after=5
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
    
    # Class constants
    SAVE_INTERVAL = 60  # Save settings every 60 seconds after changes
    PROCESSING_CLEANUP_DELAY = 5  # Clean up processing IDs after 5 seconds
    LINK_FETCH_TIMEOUT = 10.0  # 10 second timeout for fetching link data
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["link_fixer"]
        self.data_manager = self.bot.data_manager

        # Caching and pattern compilation
        self.settings_cache: Dict = {}
        self.website_map: Dict[str, Website] = {}
        self.combined_pattern: Optional[re.Pattern] = None
        self.markdown_link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        
        # Persistent save system
        self._is_dirty = asyncio.Event()
        self._save_lock = asyncio.Lock()
        self.save_task: Optional[asyncio.Task] = None
        
        # Rate limiting - prevent duplicate processing
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
        self.logger.info("Loading link fixer settings...")
        
        # Load cached settings
        self.settings_cache = await self.data_manager.get_data("link_fixer_settings") or {}
        
        # Build combined regex pattern for all websites
        patterns = []
        for name, website_class in all_websites.items():
            patterns.append(f"(?P<{name}>{website_class.pattern.pattern})")
            self.website_map[name] = website_class
        
        if patterns:
            self.combined_pattern = re.compile("|".join(patterns), re.IGNORECASE)
            self.logger.info(f"Compiled pattern for {len(patterns)} websites: {', '.join(all_websites.keys())}")
        else:
            self.logger.warning("No website patterns available")
        
        # Start periodic save task
        self.save_task = self.bot.loop.create_task(self._periodic_save())
        self.logger.info("Link fixer loaded successfully")

    async def cog_unload(self):
        """Clean up tasks and perform final save."""
        self.logger.info("Unloading link fixer...")
        
        if self.save_task:
            self.save_task.cancel()
            try:
                await self.save_task
            except asyncio.CancelledError:
                pass
        
        # Final save if there are unsaved changes
        if self._is_dirty.is_set():
            self.logger.info("Performing final save for link fixer settings...")
            async with self._save_lock:
                await self.data_manager.save_data("link_fixer_settings", self.settings_cache)

    async def _periodic_save(self):
        """Background task to periodically save settings."""
        while not self.bot.is_closed():
            try:
                await self._is_dirty.wait()
                await asyncio.sleep(self.SAVE_INTERVAL)
                
                async with self._save_lock:
                    await self.data_manager.save_data("link_fixer_settings", self.settings_cache)
                    self._is_dirty.clear()
                    self.logger.debug("Saved link fixer settings")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in link fixer periodic save: {e}", exc_info=True)
                await asyncio.sleep(self.SAVE_INTERVAL * 2)  # Wait longer after error

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
        
        # Check if entire message is spoiler-tagged
        is_spoiler = content.strip().startswith('||') and content.strip().endswith('||')
        
        # Remove markdown link syntax [text](url) to extract URLs for matching
        plain_content = self.markdown_link_pattern.sub(r'\2', content)
        
        # Find all matching links
        matches = list(self.combined_pattern.finditer(plain_content))
        if not matches:
            return False

        # Mark message as being processed
        self._processing_messages.add(message.id)
        
        try:
            # Process each link found
            for match in matches:
                asyncio.create_task(
                    self._process_link_fix_safe(message, match, is_spoiler)
                )
        finally:
            # Schedule cleanup of processing ID
            asyncio.create_task(self._cleanup_processing_id(message.id))
        
        return True

    async def _cleanup_processing_id(self, message_id: int):
        """Remove message ID from processing set after a delay."""
        await asyncio.sleep(self.PROCESSING_CLEANUP_DELAY)
        self._processing_messages.discard(message_id)

    async def _process_link_fix_safe(self, message: discord.Message, 
                                     match: re.Match, is_spoiler: bool):
        """Wrapper for process_link_fix with error handling."""
        try:
            await self.process_link_fix(message, match, is_spoiler)
        except Exception as e:
            self.logger.error(
                f"Unhandled error processing link: {e}", 
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
        if not self._is_user_opted_in(message.guild.id, message.author.id, website_name):
            return

        # Add processing reaction
        await self._add_reaction(message, "⏳")

        try:
            # Get fixed link data with timeout
            link_data = await asyncio.wait_for(
                website_class.get_links(match, session=self.bot.http_session),
                timeout=self.LINK_FETCH_TIMEOUT
            )
            
            if not link_data:
                return

            # Format and send response
            response_content = self._format_response(link_data)

            # Apply spoiler tags if needed
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
            await self._suppress_original_embed(message)
                
        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout fetching {website_name} link")
        except Exception as e:
            self.logger.error(f"Failed to fix {website_name} link: {e}", exc_info=True)
        finally:
            # Remove processing reaction
            await self._remove_reaction(message, "⏳")

    def _is_user_opted_in(self, guild_id: int, user_id: int, website_name: str) -> bool:
        """Check if user has opted in for this website's link fixing."""
        user_settings = (
            self.settings_cache
            .get(str(guild_id), {})
            .get("users", {})
            .get(str(user_id), {})
        )
        return user_settings.get(website_name, True)  # Default to enabled

    async def _add_reaction(self, message: discord.Message, emoji: str):
        """Add a reaction to a message, ignoring errors."""
        try:
            await message.add_reaction(emoji)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _remove_reaction(self, message: discord.Message, emoji: str):
        """Remove a reaction from a message, ignoring errors."""
        try:
            await message.remove_reaction(emoji, self.bot.user)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _suppress_original_embed(self, message: discord.Message):
        """Suppress the embed on the original message if we have permission."""
        if message.channel.permissions_for(message.guild.me).manage_messages:
            try:
                await message.edit(suppress=True)
            except discord.HTTPException:
                pass
    
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
        
        # Update user preference
        user_settings = self.settings_cache[guild_id]["users"][user_id]
        new_state_bool = (state == "on")
        user_settings[website] = new_state_bool
        
        # Mark as dirty for periodic save
        self._is_dirty.set()
        
        # Send confirmation
        response_msg = (
            self.personality.get('personal_opt_in', 'Link fixing has been enabled.') 
            if new_state_bool 
            else self.personality.get('personal_opt_out', 'Link fixing has been disabled.')
        )
        await interaction.followup.send(
            response_msg.replace("link fixing", f"**{website.title()}** link fixing")
        )


async def setup(bot):
    await bot.add_cog(LinkFixer(bot))