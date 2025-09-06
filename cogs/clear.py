import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Callable, Any
from .bot_admin import BotAdmin

# Personality Responses for this Cog
PERSONALITY = {
    "clear_success": "Done. I've deleted `{count}` messages. The channel looks much cleaner now.",
    "clear_user_success": "Alright, I got rid of `{count}` of {user}'s messages. Happy now?",
    "eat_start_set": "Start point set. Now reply to the end message with `!tika end`.",
    "eat_success": "Done. I ate `{count}` messages between the two points. Hope they were tasty.",
    "end_no_start": "I can't end what hasn't been started. Use `!tika eat` by replying to a message first.",
    "must_reply": "You have to reply to a message for that to work. Obviously.",
    "error_forbidden": "I can't do that. I'm missing the 'Manage Messages' permission.",
    "error_general": "Something went wrong. The messages might be too old, or Discord is just having a moment.",
    "error_not_found": "Couldn't find one of the messages you replied to. Starting over.",
    "search_started": "Searching for messages containing: `{target}`. This might take a moment...",
    "search_completed": "Found and deleted `{count}` messages containing: `{target}`",
    "search_no_matches": "No messages found containing: `{target}`. Nothing to delete.",
    "search_cancelled": "Search and delete operation cancelled.",
    "search_timeout": "Confirmation timed out. Operation cancelled.",
    "invalid_regex": "Invalid regex pattern: {error}"
}

class SearchConfirmationView(discord.ui.View):
    __slots__ = ('messages_to_delete', 'target', 'confirmed')
    
    def __init__(self, messages_to_delete: List[discord.Message], target: str):
        super().__init__(timeout=60.0)
        self.messages_to_delete = messages_to_delete
        self.target = target
        self.confirmed = False

    @discord.ui.button(label="Delete All", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        try:
            deleted_count = await self._bulk_delete_messages(interaction.channel)
            self.confirmed = True
            self.stop()
            
            await interaction.followup.send(
                PERSONALITY["search_completed"].format(count=deleted_count, target=self.target),
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(PERSONALITY["error_forbidden"], ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"{PERSONALITY['error_general']} Error: {str(e)}", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(PERSONALITY["search_cancelled"], ephemeral=True)
        self.stop()

    async def _bulk_delete_messages(self, channel: discord.TextChannel) -> int:
        """Efficiently delete messages using bulk operations when possible."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=14)
        recent_messages = [msg for msg in self.messages_to_delete if msg.created_at > cutoff_date]
        old_messages = [msg for msg in self.messages_to_delete if msg.created_at <= cutoff_date]
        
        deleted_count = 0
        
        # Bulk delete recent messages (Discord API allows bulk delete for messages < 14 days)
        for i in range(0, len(recent_messages), 100):
            chunk = recent_messages[i:i+100]
            try:
                if len(chunk) == 1:
                    await chunk[0].delete()
                else:
                    await channel.delete_messages(chunk)
                deleted_count += len(chunk)
                
                # Rate limit protection
                if i + 100 < len(recent_messages):
                    await asyncio.sleep(0.5)
            except discord.NotFound:
                # Some messages might have been deleted already
                continue
        
        # Individual delete for old messages
        for msg in old_messages:
            try:
                await msg.delete()
                deleted_count += 1
                await asyncio.sleep(0.1)  # Prevent rate limiting
            except discord.NotFound:
                continue  # Already deleted
        
        return deleted_count

    async def on_timeout(self):
        """Disable all buttons when the view times out."""
        for item in self.children:
            item.disabled = True

class MessageMatcher:
    """Optimized message matching with compiled patterns."""
    
    __slots__ = ('_compiled_patterns',)
    
    def __init__(self):
        self._compiled_patterns = {}
    
    def get_matcher(self, target: str, match_type: str) -> Callable[[str], bool]:
        """Get an optimized matcher function for the given target and type."""
        cache_key = (target, match_type)
        
        if cache_key not in self._compiled_patterns:
            self._compiled_patterns[cache_key] = self._compile_matcher(target, match_type)
        
        return self._compiled_patterns[cache_key]
    
    def _compile_matcher(self, target: str, match_type: str) -> Callable[[str], bool]:
        """Compile an optimized matcher function."""
        target_lower = target.lower()
        
        if match_type == "contains":
            return lambda content: target_lower in content.lower()
        elif match_type == "word":
            pattern = re.compile(r'\b' + re.escape(target_lower) + r'\b', re.IGNORECASE)
            return lambda content: bool(pattern.search(content))
        elif match_type == "exact":
            return lambda content: content.strip().lower() == target_lower
        elif match_type == "regex":
            try:
                pattern = re.compile(target, re.IGNORECASE)
                return lambda content: bool(pattern.search(content))
            except re.error as e:
                raise ValueError(f"Invalid regex: {e}")
        
        # Fallback to contains
        return lambda content: target_lower in content.lower()

class Clear(commands.Cog):
    __slots__ = ('bot', 'eat_start_points', '_message_matcher')
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.eat_start_points: dict[int, int] = {}
        self._message_matcher = MessageMatcher()

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Universal check for prefix commands."""
        if not ctx.guild:
            return False
        
        # Check if user is admin or bot admin
        if ctx.author.guild_permissions.administrator:
            return True
            
        bot_admin_cog = self.bot.get_cog('BotAdmin')
        if bot_admin_cog:
            guild_admins = bot_admin_cog.bot_admins.get(str(ctx.guild.id), set())
            return ctx.author.id in guild_admins
        
        return False

    @staticmethod
    def _create_preview_text(matched_messages: List[discord.Message], target: str, 
                           channel: Optional[discord.TextChannel], user: Optional[discord.Member]) -> str:
        """Create preview text for confirmation dialog."""
        preview_text = f"**Found {len(matched_messages)} messages containing:** `{target}`"
        
        if channel:
            preview_text += f" in {channel.mention}"
        if user:
            preview_text += f" from {user.mention}"
            
        preview_text += "\n\n**Preview (first 3 matches):**"
        
        for msg in matched_messages[:3]:
            # Truncate and clean content for preview
            content_preview = msg.content.replace('\n', ' ')[:100]
            if len(msg.content) > 100:
                content_preview += "..."
            preview_text += f"\n• **{msg.author.display_name}**: {content_preview}"
        
        if len(matched_messages) > 3:
            preview_text += f"\n... and {len(matched_messages) - 3} more messages"
        
        preview_text += "\n\n⚠️ **This action cannot be undone!**"
        return preview_text

    async def _search_messages(self, channel: discord.TextChannel, target: str, match_type: str,
                              user: Optional[discord.Member], limit: int) -> List[discord.Message]:
        """Efficiently search for matching messages."""
        try:
            matcher = self._message_matcher.get_matcher(target, match_type)
        except ValueError as e:
            raise ValueError(str(e))
        
        matched_messages = []
        bot_id = self.bot.user.id
        user_id = user.id if user else None
        processed_count = 0
        
        try:
            async for message in channel.history(limit=limit):
                processed_count += 1
                
                # Skip bot's own messages and apply user filter
                if message.author.id == bot_id or (user_id and message.author.id != user_id):
                    continue
                
                # Skip system messages (joins, pins, etc.)
                if message.type != discord.MessageType.default:
                    continue
                    
                if matcher(message.content):
                    matched_messages.append(message)
                
                # Add progress tracking for large searches
                if processed_count % 1000 == 0:
                    await asyncio.sleep(0.1)  # Prevent blocking
                    
        except discord.Forbidden:
            raise discord.Forbidden(None, "Missing permission to read message history")
        except discord.HTTPException as e:
            raise discord.HTTPException(None, f"Failed to fetch messages: {e}")
        
        return matched_messages

    async def _handle_deletion_error(self, interaction: discord.Interaction, error: Exception):
        """Handle deletion errors consistently."""
        if isinstance(error, discord.Forbidden):
            await interaction.followup.send(PERSONALITY["error_forbidden"], ephemeral=True)
        elif isinstance(error, discord.HTTPException):
            await interaction.followup.send(f"{PERSONALITY['error_general']} Error: {str(error)}", ephemeral=True)
        else:
            await interaction.followup.send(PERSONALITY["error_general"], ephemeral=True)

    # Main Commands
    @app_commands.command(name="clear", description="Deletes a specified number of recent messages.")
    @app_commands.describe(
        amount="The number of messages to delete (1-100).",
        user="Optional: Filter to only delete messages from this user."
    )
    @BotAdmin.is_bot_admin()
    async def slash_clear(self, interaction: discord.Interaction, 
                         amount: app_commands.Range[int, 1, 100], 
                         user: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        
        try:
            check = (lambda m: m.author == user) if user else None
            deleted_messages = await interaction.channel.purge(limit=amount, check=check, bulk=True)
            
            if user:
                response = PERSONALITY["clear_user_success"].format(count=len(deleted_messages), user=user.mention)
            else:
                response = PERSONALITY["clear_success"].format(count=len(deleted_messages))
                
            await interaction.followup.send(response, ephemeral=True)
            
        except (discord.Forbidden, discord.HTTPException) as e:
            await self._handle_deletion_error(interaction, e)

    @app_commands.command(name="clearsearch", description="Search and delete messages containing specific text or links.")
    @app_commands.describe(
        target="The text, word, or link to search for and delete.",
        match_type="How to match the target text.",
        channel="Optional: Search in a specific channel (defaults to current channel).",
        user="Optional: Only search messages from this user.",
        limit="Maximum number of messages to search through (default: 1000).",
        preview="Preview matches before deleting (recommended for large operations)."
    )
    @app_commands.choices(match_type=[
        app_commands.Choice(name="Contains (text appears anywhere)", value="contains"),
        app_commands.Choice(name="Whole Word (exact word boundaries)", value="word"),
        app_commands.Choice(name="Exact Match (entire message)", value="exact"),
        app_commands.Choice(name="Regex Pattern (advanced)", value="regex")
    ])
    @BotAdmin.is_bot_admin()
    async def clear_search(self, interaction: discord.Interaction, target: str,
                          match_type: str = "contains",
                          channel: Optional[discord.TextChannel] = None,
                          user: Optional[discord.Member] = None,
                          limit: app_commands.Range[int, 1, 10000] = 1000,
                          preview: bool = True):
        await interaction.response.defer(ephemeral=True)
        
        search_channel = channel or interaction.channel
        
        # Validate regex pattern early
        if match_type == "regex":
            try:
                re.compile(target)
            except re.error as e:
                await interaction.followup.send(
                    PERSONALITY["invalid_regex"].format(error=str(e)), 
                    ephemeral=True
                )
                return
        
        # Search for matching messages
        await interaction.followup.send(
            PERSONALITY["search_started"].format(target=target), 
            ephemeral=True
        )
        
        try:
            matched_messages = await self._search_messages(search_channel, target, match_type, user, limit)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send(PERSONALITY["error_forbidden"], ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"{PERSONALITY['error_general']} Error: {str(e)}", ephemeral=True)
            return
        
        if not matched_messages:
            await interaction.followup.send(
                PERSONALITY["search_no_matches"].format(target=target), 
                ephemeral=True
            )
            return
        
        if preview:
            # Show confirmation dialog with preview
            preview_text = self._create_preview_text(matched_messages, target, channel, user)
            view = SearchConfirmationView(matched_messages, target)
            await interaction.followup.send(preview_text, view=view, ephemeral=True)
            
            if await view.wait():
                await interaction.followup.send(PERSONALITY["search_timeout"], ephemeral=True)
        else:
            # Direct deletion without preview (not recommended for large batches)
            try:
                view = SearchConfirmationView(matched_messages, target)
                deleted_count = await view._bulk_delete_messages(search_channel)
                await interaction.followup.send(
                    PERSONALITY["search_completed"].format(count=deleted_count, target=target),
                    ephemeral=True
                )
            except Exception as e:
                await self._handle_deletion_error(interaction, e)

    # Eat Commands (Range Deletion)
    @commands.command()
    async def eat(self, ctx: commands.Context):
        """Set the starting message for range deletion."""
        if not ctx.message.reference:
            await ctx.send(PERSONALITY["must_reply"], delete_after=10)
        else:
            self.eat_start_points[ctx.channel.id] = ctx.message.reference.message_id
            await ctx.send(PERSONALITY["eat_start_set"], delete_after=10)
        await ctx.message.delete()

    @commands.command()
    async def end(self, ctx: commands.Context):
        """Set the end message and execute range deletion."""
        if not ctx.message.reference:
            await ctx.send(PERSONALITY["must_reply"], delete_after=10)
            await ctx.message.delete()
            return

        start_id = self.eat_start_points.pop(ctx.channel.id, None)
        if not start_id:
            await ctx.send(PERSONALITY["end_no_start"], delete_after=10)
            await ctx.message.delete()
            return

        end_id = ctx.message.reference.message_id
        await ctx.message.delete()

        try:
            start_msg = await ctx.channel.fetch_message(start_id)
            end_msg = await ctx.channel.fetch_message(end_id)
        except discord.NotFound:
            await ctx.send(PERSONALITY["error_not_found"], delete_after=10)
            return

        # Ensure correct order
        if start_msg.created_at > end_msg.created_at:
            start_msg, end_msg = end_msg, start_msg

        # Collect messages in range
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=14)
        messages_to_delete = []
        
        async for msg in ctx.channel.history(limit=None, after=start_msg, before=end_msg):
            if msg.created_at > cutoff_date:
                messages_to_delete.append(msg)
        
        # Include boundary messages if recent enough
        for boundary_msg in [start_msg, end_msg]:
            if boundary_msg.created_at > cutoff_date:
                messages_to_delete.append(boundary_msg)
        
        if not messages_to_delete:
            await ctx.send("No recent messages found in that range to delete.", delete_after=10)
            return

        try:
            # Bulk delete in chunks
            for i in range(0, len(messages_to_delete), 100):
                chunk = messages_to_delete[i:i+100]
                await ctx.channel.delete_messages(chunk)
            
            await ctx.send(PERSONALITY["eat_success"].format(count=len(messages_to_delete)), delete_after=10)
        except discord.Forbidden:
            await ctx.send(PERSONALITY["error_forbidden"], delete_after=10)
        except discord.HTTPException:
            await ctx.send(PERSONALITY["error_general"], delete_after=10)

async def setup(bot):
    await bot.add_cog(Clear(bot))
    # why is this always used for emote spam or cus of Andy and Ori :pensivewobble: