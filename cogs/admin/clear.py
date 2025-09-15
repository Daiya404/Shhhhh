# cogs/admin/clear.py
import logging
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import re
from datetime import timedelta
from typing import Optional, List, Dict, Callable, Union

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

# --- Helper Classes ---
class SearchConfirmationView(discord.ui.View):
    __slots__ = ('messages_to_delete', 'confirmed', 'personality', 'response_text')
    
    def __init__(self, messages_to_delete: List[discord.Message], personality: dict, response_text: str):
        super().__init__(timeout=120.0)
        self.messages_to_delete = messages_to_delete
        self.confirmed = False
        self.personality = personality
        self.response_text = response_text

    async def _bulk_delete_messages(self, channel: discord.TextChannel) -> int:
        cutoff = discord.utils.utcnow() - timedelta(days=14)
        recent = [msg for msg in self.messages_to_delete if msg.created_at > cutoff]
        old = [msg for msg in self.messages_to_delete if msg.created_at <= cutoff]
        
        deleted_count = 0
        if recent:
            for chunk in discord.utils.as_chunks(recent, 100):
                try:
                    await channel.delete_messages(chunk)
                    deleted_count += len(chunk)
                except (discord.NotFound, discord.HTTPException):
                    # Fallback: If bulk fails, try one-by-one for this chunk
                    for msg in chunk:
                        try: 
                            await msg.delete()
                            deleted_count += 1
                        except (discord.NotFound, discord.HTTPException): pass
                await asyncio.sleep(0.5) # Prevent rate-limiting
        
        for msg in old:
            try:
                await msg.delete()
                deleted_count += 1
                await asyncio.sleep(0.2)
            except (discord.NotFound, discord.HTTPException): continue
        return deleted_count

    @discord.ui.button(label="Delete All", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        deleted_count = await self._bulk_delete_messages(interaction.channel)
        self.confirmed = True
        for item in self.children: item.disabled = True
        
        response = self.response_text.format(count=deleted_count)
        await interaction.edit_original_response(content=response, view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content=self.personality["search_cancelled"], view=self)
        self.stop()

class MessageMatcher:
    # This class is already highly optimized.
    __slots__ = ('_compiled_patterns',)
    def __init__(self): self._compiled_patterns = {}
    def get_matcher(self, target: str, match_type: str) -> Callable[[str], bool]:
        cache_key = (target, match_type)
        if cache_key in self._compiled_patterns: return self._compiled_patterns[cache_key]
        self._compiled_patterns[cache_key] = self._compile_matcher(target, match_type)
        return self._compiled_patterns[cache_key]
    def _compile_matcher(self, target: str, match_type: str) -> Callable[[str], bool]:
        target_lower = target.lower()
        if match_type == "contains": return lambda c: target_lower in c.lower()
        if match_type == "word": pattern = re.compile(r'\b' + re.escape(target_lower) + r'\b', re.IGNORECASE); return lambda c: bool(pattern.search(c))
        if match_type == "exact": return lambda c: c.strip().lower() == target_lower
        if match_type == "regex":
            try: pattern = re.compile(target, re.IGNORECASE); return lambda c: bool(pattern.search(c))
            except re.error as e: raise ValueError(f"Invalid regex: {e}")
        return lambda c: target_lower in c.lower()

# --- The Main Cog ---
class Clear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["clear"]
        self._message_matcher = MessageMatcher()
        self.range_points: Dict[str, int] = {} # key: f"{user_id}:{channel_id}"
        
        self.set_start_point_menu = app_commands.ContextMenu(name="Set as Deletion Start", callback=self.set_start_point)
        self.set_end_point_menu = app_commands.ContextMenu(name="Set as Deletion End", callback=self.set_end_point)
        self.bot.tree.add_command(self.set_start_point_menu)
        self.bot.tree.add_command(self.set_end_point_menu)

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """A local check to see if the clear_commands feature is enabled."""
        feature_manager = self.bot.get_cog("FeatureManager")
        # The feature name here MUST match the one in AVAILABLE_FEATURES
        feature_name = "clear_commands" 
        
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, feature_name):
            # This personality response is just a suggestion; you can create a generic one.
            await interaction.response.send_message(f"Hmph. The {feature_name.replace('_', ' ').title()} feature is disabled on this server.", ephemeral=True)
            return False
        return True

    async def cog_unload(self):
        self.bot.tree.remove_command(self.set_start_point_menu.name, type=self.set_start_point_menu.type)
        self.bot.tree.remove_command(self.set_end_point_menu.name, type=self.set_end_point_menu.type)

    async def cog_check(self, ctx: commands.Context) -> bool:
        """
        This check now runs for ALL prefix commands in this cog (e.g., !tika eat).
        It now verifies BOTH admin permissions AND the feature manager status.
        """
        if not ctx.guild:
            return False

        # 1. Check for Bot Admin permissions first.
        admin_cog = self.bot.get_cog("BotAdmin")
        if not admin_cog or not await admin_cog.check_prefix_command(ctx):
            return False
            
        # 2. Check if the 'clear_commands' feature is enabled.
        feature_manager = self.bot.get_cog("FeatureManager")
        if not feature_manager or not feature_manager.is_feature_enabled(ctx.guild.id, "clear_commands"):
            # For prefix commands, we usually fail silently instead of sending a message.
            return False

        # If both checks pass, the command is allowed.
        return True

    # --- Slash Commands ---
    @app_commands.command(name="clear", description="Deletes a specified number of recent messages.")
    @app_commands.default_permissions(manage_messages=True)
    @is_bot_admin()
    @app_commands.describe(amount="The number of messages to delete (1-100).", user="Optional: Filter to only delete messages from this user.")
    async def slash_clear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], user: Optional[discord.Member] = None):
        if not await self._is_feature_enabled(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            check = (lambda m: m.author == user) if user else None
            deleted = await interaction.channel.purge(limit=amount, check=check, bulk=True)
            response = self.personality["clear_user_success"].format(count=len(deleted), user=user.mention) if user else self.personality["clear_success"].format(count=len(deleted))
            await interaction.followup.send(response)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.followup.send(self.personality["error_forbidden"] if isinstance(e, discord.Forbidden) else self.personality["error_general"])

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
        if not await self._is_feature_enabled(interaction):
            return
        await interaction.response.send_message(f"🔍 Searching for messages containing `{target}`...", ephemeral=True)
        try:
            matcher = self._message_matcher.get_matcher(target, match_type)
            matched = []
            scanned = 0
            async for msg in interaction.channel.history(limit=limit):
                scanned += 1
                if limit > 2000 and scanned % 1000 == 0: await interaction.edit_original_response(content=f"🔍 Searching... (Scanned {scanned}/{limit} messages)")
                if user and msg.author.id != user.id: continue
                if msg.type != discord.MessageType.default: continue
                if matcher(msg.content): matched.append(msg)
        except ValueError as e: return await interaction.edit_original_response(content=str(e))
        except Exception: return await interaction.edit_original_response(content=self.personality["error_general"])
        if not matched: return await interaction.edit_original_response(content=self.personality["search_no_matches"].format(target=target))
        
        preview = self._create_preview_text(matched, target, user)
        response_text = self.personality["search_completed"].format(count="{count}", target=target)
        view = SearchConfirmationView(matched, self.personality, response_text)
        await interaction.edit_original_response(content=preview, view=view)

    # --- Context Menu & Prefix Commands for Range Deletion ---
    @is_bot_admin()
    async def set_start_point(self, interaction: discord.Interaction, message: discord.Message):
        if not await self._is_feature_enabled(interaction):
            return
        key = f"{interaction.user.id}:{interaction.channel_id}"
        self.range_points[key] = message.id
        await interaction.response.send_message(f"✅ Start point set. Now use `Set as Deletion End` on another message.", ephemeral=True)

    @commands.command(aliases=['start'])
    async def eat(self, ctx: commands.Context):
        if not ctx.message.reference:
            await ctx.send(self.personality["must_reply"], delete_after=10)
        else:
            key = f"{ctx.author.id}:{ctx.channel.id}"
            self.range_points[key] = ctx.message.reference.message_id
            await ctx.send(self.personality["eat_start_set"], delete_after=10)
        await ctx.message.delete()

    @is_bot_admin()
    async def set_end_point(self, interaction: discord.Interaction, message: discord.Message):
        if not await self._is_feature_enabled(interaction):
            return
        key = f"{interaction.user.id}:{interaction.channel_id}"
        start_id = self.range_points.pop(key, None)
        if not start_id: return await interaction.response.send_message("❌ You need to set a start point first!", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self._perform_range_deletion(interaction, start_id, message.id)

    @commands.command()
    async def end(self, ctx: commands.Context):
        await ctx.message.delete()
        if not ctx.message.reference: return await ctx.send(self.personality["must_reply"], delete_after=10)
        
        key = f"{ctx.author.id}:{ctx.channel.id}"
        start_id = self.range_points.pop(key, None)
        if not start_id: return await ctx.send(self.personality["end_no_start"], delete_after=10)
        
        await self._perform_range_deletion(ctx, start_id, ctx.message.reference.message_id)

    # --- Core Deletion Logic ---
    async def _perform_range_deletion(self, source: Union[discord.Interaction, commands.Context], start_id: int, end_id: int):
        channel = source.channel
        try:
            start_msg = await channel.fetch_message(start_id)
            end_msg = await channel.fetch_message(end_id)
            if start_msg.created_at > end_msg.created_at: start_msg, end_msg = end_msg, start_msg

            # *** THE OPTIMIZATION ***
            # Use purge directly instead of iterating. This is massively faster.
            deleted = await channel.purge(before=end_msg, after=start_msg, limit=None)
            await start_msg.delete()
            await end_msg.delete()
            
            count = len(deleted) + 2
            response = self.personality["eat_success"].format(count=count)
            
            if isinstance(source, discord.Interaction): await source.followup.send(response, ephemeral=True)
            else: await source.send(response, delete_after=10)

        except discord.NotFound:
            response = self.personality["error_not_found"]
            if isinstance(source, discord.Interaction): await source.followup.send(response, ephemeral=True)
            else: await source.send(response, delete_after=10)
        except discord.Forbidden:
            response = self.personality["error_forbidden"]
            if isinstance(source, discord.Interaction): await source.followup.send(response, ephemeral=True)
            else: await source.send(response, delete_after=10)
        except Exception:
            response = self.personality["error_general"]
            if isinstance(source, discord.Interaction): await source.followup.send(response, ephemeral=True)
            else: await source.send(response, delete_after=10)

    # --- Helper Methods ---
    def _create_preview_text(self, matched_messages: List[discord.Message], target: str, user: Optional[discord.Member]) -> str:
        text = f"**Found {len(matched_messages)} messages containing:** `{target}`"
        if user: text += f" from {user.mention}"
        text += "\n\n**Preview (first 3 matches):**"
        for msg in matched_messages[:3]:
            preview = discord.utils.escape_markdown(msg.content.replace('\n', ' ')[:100])
            text += f"\n• **{msg.author.display_name}**: {preview}" + ("..." if len(msg.content) > 100 else "")
        if len(matched_messages) > 3: text += f"\n... and {len(matched_messages) - 3} more messages"
        text += "\n\n⚠️ **This action cannot be undone!**"
        return text

async def setup(bot):
    await bot.add_cog(Clear(bot))