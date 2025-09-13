# cogs/admin/clear.py
import logging
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Callable

from config.personalities import PERSONALITY_RESPONSES
# Correctly import the standalone decorator function
from cogs.admin.bot_admin import is_bot_admin

# --- Helper Classes (self-contained, no changes needed from original) ---

class SearchConfirmationView(discord.ui.View):
    __slots__ = ('messages_to_delete', 'target', 'confirmed', 'personality')
    
    def __init__(self, messages_to_delete: List[discord.Message], target: str, personality: dict):
        super().__init__(timeout=60.0)
        self.messages_to_delete = messages_to_delete
        self.target = target
        self.confirmed = False
        self.personality = personality

    @discord.ui.button(label="Delete All", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        try:
            deleted_count = await self._bulk_delete_messages(interaction.channel)
            self.confirmed = True
            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(view=self)
            await interaction.followup.send(
                self.personality["search_completed"].format(count=deleted_count, target=self.target),
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(self.personality["error_forbidden"], ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"{self.personality['error_general']} Error: {str(e)}", ephemeral=True)
        finally:
            self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=self.personality["search_cancelled"], view=self)
        self.stop()

    async def _bulk_delete_messages(self, channel: discord.TextChannel) -> int:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=14)
        recent_messages = [msg for msg in self.messages_to_delete if msg.created_at > cutoff_date]
        old_messages = [msg for msg in self.messages_to_delete if msg.created_at <= cutoff_date]
        
        deleted_count = 0
        
        for i in range(0, len(recent_messages), 100):
            chunk = recent_messages[i:i+100]
            try:
                if len(chunk) > 1:
                    await channel.delete_messages(chunk)
                elif len(chunk) == 1:
                    await chunk[0].delete()
                deleted_count += len(chunk)
                if i + 100 < len(recent_messages):
                    await asyncio.sleep(0.5)
            except (discord.NotFound, discord.HTTPException):
                continue
        
        for msg in old_messages:
            try:
                await msg.delete()
                deleted_count += 1
                await asyncio.sleep(0.1)
            except (discord.NotFound, discord.HTTPException):
                continue
        
        return deleted_count

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

class MessageMatcher:
    __slots__ = ('_compiled_patterns',)
    
    def __init__(self):
        self._compiled_patterns = {}
    
    def get_matcher(self, target: str, match_type: str) -> Callable[[str], bool]:
        cache_key = (target, match_type)
        if cache_key not in self._compiled_patterns:
            self._compiled_patterns[cache_key] = self._compile_matcher(target, match_type)
        return self._compiled_patterns[cache_key]
    
    def _compile_matcher(self, target: str, match_type: str) -> Callable[[str], bool]:
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
        return lambda content: target_lower in content.lower()

# --- The Main Cog ---

class Clear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["clear"]
        self.eat_start_points: dict[int, int] = {}
        self._message_matcher = MessageMatcher()

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Universal check for prefix commands (!tika eat/end)."""
        if not ctx.guild: return False
        
        admin_cog = self.bot.get_cog("BotAdmin")
        if not admin_cog:
            self.logger.warning("BotAdmin cog not found for prefix command check.")
            return False
        
        # This now calls the simplified, correct method.
        return await admin_cog.check_prefix_command(ctx)

    @staticmethod
    def _create_preview_text(matched_messages: List[discord.Message], target: str, 
                           channel: Optional[discord.TextChannel], user: Optional[discord.Member]) -> str:
        preview_text = f"**Found {len(matched_messages)} messages containing:** `{target}`"
        if channel: preview_text += f" in {channel.mention}"
        if user: preview_text += f" from {user.mention}"
        preview_text += "\n\n**Preview (first 3 matches):**"
        for msg in matched_messages[:3]:
            content_preview = msg.content.replace('\n', ' ')[:100]
            if len(msg.content) > 100: content_preview += "..."
            preview_text += f"\n• **{msg.author.display_name}**: {content_preview}"
        if len(matched_messages) > 3:
            preview_text += f"\n... and {len(matched_messages) - 3} more messages"
        preview_text += "\n\n⚠️ **This action cannot be undone!**"
        return preview_text

    async def _search_messages(self, channel: discord.TextChannel, target: str, match_type: str,
                              user: Optional[discord.Member], limit: int) -> List[discord.Message]:
        matcher = self._message_matcher.get_matcher(target, match_type)
        matched_messages, bot_id = [], self.bot.user.id
        user_id = user.id if user else None
        
        async for message in channel.history(limit=limit):
            if message.author.id == bot_id or (user_id and message.author.id != user_id):
                continue
            if message.type != discord.MessageType.default:
                continue
            if matcher(message.content):
                matched_messages.append(message)
        return matched_messages

    async def _handle_deletion_error(self, interaction: discord.Interaction, error: Exception):
        msg = self.personality["error_general"]
        if isinstance(error, discord.Forbidden): msg = self.personality["error_forbidden"]
        elif isinstance(error, discord.HTTPException): msg += f" Error: {str(error)}"
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="clear", description="Deletes a specified number of recent messages.")
    @app_commands.default_permissions(manage_messages=True)
    @is_bot_admin()
    @app_commands.describe(amount="The number of messages to delete (1-100).", user="Optional: Filter to only delete messages from this user.")
    async def slash_clear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], user: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        try:
            check = (lambda m: m.author == user) if user else None
            deleted_messages = await interaction.channel.purge(limit=amount, check=check, bulk=True)
            response = self.personality["clear_user_success"].format(count=len(deleted_messages), user=user.mention) if user else self.personality["clear_success"].format(count=len(deleted_messages))
            await interaction.followup.send(response)
        except (discord.Forbidden, discord.HTTPException) as e:
            await self._handle_deletion_error(interaction, e)

    @app_commands.command(name="clearsearch", description="Search and delete messages containing specific text or links.")
    @app_commands.default_permissions(manage_messages=True)
    @is_bot_admin()
    @app_commands.describe(target="The text to search for.", match_type="How to match the text.", user="Optional: Only search messages from this user.", limit="Maximum messages to search (default: 1000).")
    @app_commands.choices(match_type=[
        app_commands.Choice(name="Contains (text appears anywhere)", value="contains"),
        app_commands.Choice(name="Whole Word (exact word boundaries)", value="word"),
        app_commands.Choice(name="Exact Match (entire message)", value="exact"),
        app_commands.Choice(name="Regex Pattern (advanced)", value="regex")
    ])
    async def clear_search(self, interaction: discord.Interaction, target: str, match_type: str = "contains", user: Optional[discord.Member] = None, limit: app_commands.Range[int, 1, 10000] = 1000):
        await interaction.response.defer(ephemeral=True)
        try:
            matched_messages = await self._search_messages(interaction.channel, target, match_type, user, limit)
        except ValueError as e: 
            return await interaction.followup.send(str(e))
        except Exception: 
            return await interaction.followup.send(self.personality["error_general"])
        
        if not matched_messages:
            return await interaction.followup.send(self.personality["search_no_matches"].format(target=target))
        
        preview_text = self._create_preview_text(matched_messages, target, None, user)
        view = SearchConfirmationView(matched_messages, target, self.personality)
        await interaction.followup.send(preview_text, view=view, ephemeral=True)
        
        timed_out = await view.wait()
        if timed_out and not view.confirmed:
            await interaction.edit_original_response(content=self.personality["search_timeout"], view=None)

    # --- Prefix Commands ---
    @commands.command()
    async def eat(self, ctx: commands.Context):
        if not ctx.message.reference:
            await ctx.send(self.personality["must_reply"], delete_after=10)
        else:
            self.eat_start_points[ctx.channel.id] = ctx.message.reference.message_id
            await ctx.send(self.personality["eat_start_set"], delete_after=10)
        await ctx.message.delete()

    @commands.command()
    async def end(self, ctx: commands.Context):
        if not ctx.message.reference:
            await ctx.message.delete()
            return await ctx.send(self.personality["must_reply"], delete_after=10)
        
        start_id = self.eat_start_points.pop(ctx.channel.id, None)
        if not start_id:
            await ctx.message.delete()
            return await ctx.send(self.personality["end_no_start"], delete_after=10)
        
        end_id = ctx.message.reference.message_id
        await ctx.message.delete()

        try:
            start_msg = await ctx.channel.fetch_message(start_id)
            end_msg = await ctx.channel.fetch_message(end_id)
        except discord.NotFound:
            return await ctx.send(self.personality["error_not_found"], delete_after=10)
        
        if start_msg.created_at > end_msg.created_at:
            start_msg, end_msg = end_msg, start_msg

        try:
            # Purge doesn't include the before/after messages, so we delete them manually
            deleted = await ctx.channel.purge(before=end_msg, after=start_msg, limit=None)
            await start_msg.delete()
            await end_msg.delete()
            await ctx.send(self.personality["eat_success"].format(count=len(deleted) + 2), delete_after=10)
        except discord.Forbidden:
            await ctx.send(self.personality["error_forbidden"], delete_after=10)
        except discord.HTTPException:
            await ctx.send(self.personality["error_general"], delete_after=10)

async def setup(bot):
    await bot.add_cog(Clear(bot))