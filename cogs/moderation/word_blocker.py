# cogs/moderation/word_blocker.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import time
from typing import Optional, List
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

class ActionType(Enum):
    DELETE_ONLY = "delete"
    WARN_DELETE = "warn_delete" 

@dataclass
class BlockedWordEntry:
    word: str
    action: ActionType
    severity: int
    created_by: int = None
    created_at: int = None

class WordBlocker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["word_blocker"]
        self.data_manager = self.bot.data_manager
        
        self.WARNING_COOLDOWN = 3.0
        self.channel_warning_cooldowns = {}
        self.blocklist_cache = {}
        self.compiled_patterns = {}
        self.user_violations = defaultdict(lambda: deque(maxlen=10))
        self.ESCALATION_WINDOW = 300
        self.performance_stats = defaultdict(int)
        self.whitelist_cache = {}

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """A local check to see if the word_blocker feature is enabled."""
        feature_manager = self.bot.get_cog("FeatureManager")
        feature_name = "word_blocker" 
        
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, feature_name):
            await interaction.response.send_message(f"Hmph. The {feature_name.replace('_', ' ').title()} feature is disabled on this server.", ephemeral=True)
            return False
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info("Loading optimized word blocker system...")
        raw_blocklist = await self.data_manager.get_data("word_blocklist")
        await self._migrate_legacy_data(raw_blocklist)
        self.whitelist_cache = await self.data_manager.get_data("word_whitelist") or {}
        for guild_id, data in self.blocklist_cache.items():
            await self._update_guild_cache(guild_id, data)
        self.logger.info(f"Word Blocker ready with {len(self.blocklist_cache)} guild configs")

    async def _migrate_legacy_data(self, raw_data: dict):
        """Migrates old list-based blocklist to the new structure with match types."""
        self.blocklist_cache = {}
        for guild_id, guild_data in raw_data.items():
            migrated_data = {
                "global": {"whole_word": {}, "exact": {}},
                "users": {},
                "settings": { "default_action": ActionType.WARN_DELETE.value }
            }
            if isinstance(guild_data.get("global"), list):
                for word in guild_data["global"]:
                    migrated_data["global"]["whole_word"][word.lower()] = {"action": ActionType.WARN_DELETE.value, "severity": 1, "created_at": int(time.time())}
            if isinstance(guild_data.get("users"), dict):
                for user_id, words in guild_data["users"].items():
                    migrated_data["users"][user_id] = {"whole_word": {}, "exact": {}}
                    if isinstance(words, list):
                        for word in words:
                            migrated_data["users"][user_id]["whole_word"][word.lower()] = {"action": ActionType.WARN_DELETE.value, "severity": 1, "created_at": int(time.time())}
            self.blocklist_cache[guild_id] = migrated_data

    async def _update_guild_cache(self, guild_id: str, guild_data: dict):
        """Updates compiled regex patterns in the cache. Only 'whole_word' needs regex."""
        try:
            global_words = list(guild_data.get("global", {}).get("whole_word", {}).keys())
            global_pattern = self._build_optimized_pattern(global_words, use_boundaries=True)
            
            user_patterns = {
                uid: self._build_optimized_pattern(list(uwords.get("whole_word", {}).keys()), use_boundaries=True) 
                for uid, uwords in guild_data.get("users", {}).items()
            }
            
            whitelist_words = list(self.whitelist_cache.get(guild_id, {}).keys())
            whitelist_pattern = self._build_optimized_pattern(whitelist_words, use_boundaries=True)
            
            self.compiled_patterns[guild_id] = {"global": global_pattern, "users": user_patterns, "whitelist": whitelist_pattern}
            self.logger.debug(f"Updated cache for guild {guild_id}")
        except Exception as e:
            self.logger.error(f"Error updating cache for guild {guild_id}: {e}")

    def _build_optimized_pattern(self, words: List[str], use_boundaries: bool = False) -> Optional[re.Pattern]:
        if not words: return None
        try:
            sorted_words = sorted(set(words), key=len, reverse=True)
            escaped = [re.escape(word) for word in sorted_words]
            core = r'(?:' + '|'.join(escaped) + r')'
            if use_boundaries: core = r'\b' + core + r'\b'
            return re.compile(core, re.IGNORECASE | re.UNICODE)
        except re.error as e:
            self.logger.error(f"Failed to compile pattern for words {words}: {e}")
            return None

    def _check_whitelist(self, content: str, guild_id: str) -> bool:
        pattern = self.compiled_patterns.get(guild_id, {}).get("whitelist")
        return bool(pattern and pattern.search(content))

    async def check_and_handle_message(self, message: discord.Message) -> bool:
        self.performance_stats["total_checks"] += 1
        if not message.guild or message.author.bot: return False

        content_lower = message.content.lower()
        content_stripped = content_lower.strip()
        
        # --- NEW: Link Whitelisting Logic ---
        if ('http://' in content_lower or 'https://' in content_lower) and 'tenor.com' not in content_lower:
            return False

        guild_id = str(message.guild.id)
        guild_data = self.blocklist_cache.get(guild_id)
        if not guild_data: return False
        
        patterns = self.compiled_patterns.get(guild_id)
        if not patterns: return False
        
        # --- 1. Exact Match Check (Fastest) ---
        user_blocks = guild_data.get("users", {}).get(str(message.author.id), {})
        if content_stripped in user_blocks.get("exact", {}):
            await self._handle_blocked_message(message, content_stripped)
            return True

        global_blocks = guild_data.get("global", {})
        if content_stripped in global_blocks.get("exact", {}):
            await self._handle_blocked_message(message, content_stripped)
            return True

        # --- 2. Whitelist Check ---
        if self._check_whitelist(message.content, guild_id): return False
        
        # --- 3. Whole Word Regex Check (Slower) ---
        triggered_word = None
        
        global_pattern = patterns.get("global")
        if global_pattern and (match := global_pattern.search(content_lower)):
            triggered_word = match.group()
            self.performance_stats["regex_cache_hits"] += 1
            
        if not triggered_word:
            user_pattern = patterns.get("users", {}).get(str(message.author.id))
            if user_pattern and (match := user_pattern.search(content_lower)):
                triggered_word = match.group()
                self.performance_stats["regex_cache_hits"] += 1

        if triggered_word:
            await self._handle_blocked_message(message, triggered_word)
            return True
        return False

    async def _handle_blocked_message(self, message: discord.Message, trigger_word: str):
        try:
            await message.delete()
            self.performance_stats["total_blocks"] += 1
        except (discord.Forbidden, discord.NotFound) as e:
            self.logger.warning(f"Failed to delete message: {e}")
            return

        self.user_violations[message.author.id].append(time.time())
        violation_level = len(self.user_violations[message.author.id])
        await self._send_warning(message, trigger_word, violation_level)

    async def _send_warning(self, message: discord.Message, trigger_word: str, violation_level: int):
        channel_id = message.channel.id
        now = time.time()
        if now - self.channel_warning_cooldowns.get(channel_id, 0) < self.WARNING_COOLDOWN: return
        
        self.channel_warning_cooldowns[channel_id] = now
        warning = f"{message.author.mention}, your message contained a blocked term (`{trigger_word}`). Watch your language."
        if violation_level > 1: warning += f" (Violation #{violation_level})"
        
        try:
            await message.channel.send(warning, delete_after=10)
        except discord.Forbidden:
            self.logger.warning(f"Cannot send warning in {message.channel.name}")

    @app_commands.command(name="blockword", description="Add or remove blocked words.")
    @is_bot_admin()
    @app_commands.describe(
        action="Add or remove a word",
        scope="Apply to everyone or a specific user",
        word="The word(s) to block/unblock, separated by spaces",
        user="Target user for user-specific blocks",
        match_type="How to block the word. Whole Word = in a sentence. Exact = only message content."
    )
    @app_commands.choices(
        action=[app_commands.Choice(name="Add", value="add"), app_commands.Choice(name="Remove", value="remove")],
        scope=[app_commands.Choice(name="Global", value="global"), app_commands.Choice(name="User-Specific", value="user")],
        match_type=[
            app_commands.Choice(name="Whole Word (in a sentence)", value="whole_word"),
            app_commands.Choice(name="Exact Match (the only word)", value="exact")
        ]
    )
    async def manage_blockword(
        self, 
        interaction: discord.Interaction, 
        action: str, 
        scope: str, 
        word: str, 
        user: Optional[discord.Member] = None, 
        match_type: str = "whole_word"
    ):
        if not await self._is_feature_enabled(interaction):
            return
        await interaction.response.defer()
        
        if scope == "user" and not user:
            return await interaction.followup.send("You must specify a user for user-specific blocks.", ephemeral=True)
            
        guild_id = str(interaction.guild.id)
        guild_data = self.blocklist_cache.setdefault(guild_id, {
            "global": {"whole_word": {}, "exact": {}}, 
            "users": {}, 
            "settings": {"default_action": "warn_delete"}
        })
        
        words_to_process = [w.strip() for w in word.lower().split() if w.strip()]
        if not words_to_process:
            return await interaction.followup.send("You must provide at least one word.", ephemeral=True)
            
        added, removed, exists, not_found = [], [], [], []
        
        if scope == "global":
            scope_dict = guild_data.setdefault("global", {"whole_word": {}, "exact": {}})
        else:
            scope_dict = guild_data.setdefault("users", {}).setdefault(str(user.id), {"whole_word": {}, "exact": {}})

        for word_key in words_to_process:
            if action == "add":
                target_dict = scope_dict.setdefault(match_type, {})
                if word_key in scope_dict.get("whole_word", {}) or word_key in scope_dict.get("exact", {}):
                    exists.append(word_key)
                else:
                    target_dict[word_key] = {"action": ActionType.WARN_DELETE.value, "severity": 1, "created_by": interaction.user.id, "created_at": int(time.time())}
                    added.append(word_key)
            else:
                removed_from_whole = scope_dict.get("whole_word", {}).pop(word_key, None)
                removed_from_exact = scope_dict.get("exact", {}).pop(word_key, None)
                if removed_from_whole or removed_from_exact:
                    removed.append(word_key)
                else:
                    not_found.append(word_key)

        await self.data_manager.save_data("word_blocklist", self.blocklist_cache)
        await self._update_guild_cache(guild_id, guild_data)
        
        response_parts = []
        target_str = f"for {user.display_name}" if user else "from the global list"
        if added: response_parts.append(f"Added (`{match_type.replace('_', ' ')}`): `{'`, `'.join(added)}` {target_str}.")
        if removed: response_parts.append(f"Removed: `{'`, `'.join(removed)}` {target_str}.")
        if exists: response_parts.append(f"Already existed: `{'`, `'.join(exists)}`.")
        if not_found: response_parts.append(f"Not found: `{'`, `'.join(not_found)}`.")
        
        await interaction.followup.send("\n".join(response_parts) or "No changes were made.")

    @app_commands.command(name="blockword-list", description="List blocked words.")
    @app_commands.describe(user="Show blocks for a specific user (admin only)")
    async def list_blockwords(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if not await self._is_feature_enabled(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild.id)
        guild_data = self.blocklist_cache.get(guild_id, {})
        
        embed = discord.Embed(color=discord.Color.red())
        
        blocks = {}
        if user:
            blocks = guild_data.get("users", {}).get(str(user.id), {})
            embed.title = f"Blocked Words for {user.display_name}"
        else:
            blocks = guild_data.get("global", {})
            embed.title = "Globally Blocked Words"

        whole_word_blocks = blocks.get("whole_word", {})
        exact_blocks = blocks.get("exact", {})

        if not whole_word_blocks and not exact_blocks:
            embed.description = "None."
        else:
            if whole_word_blocks:
                ww_list = ", ".join(f"`{word}`" for word in sorted(whole_word_blocks.keys()))
                embed.add_field(name="Blocked in Sentences (Whole Word)", value=ww_list or "None", inline=False)
            if exact_blocks:
                e_list = ", ".join(f"`{word}`" for word in sorted(exact_blocks.keys()))
                embed.add_field(name="Blocked as Exact Message", value=e_list or "None", inline=False)
        
        await interaction.followup.send(embed=embed)
        
    @app_commands.command(name="blockword-settings", description="Configure word blocker settings.")
    @is_bot_admin()
    @app_commands.describe(default_action="Default action for new blocked words")
    @app_commands.choices(default_action=[app_commands.Choice(name="Warn & Delete", value="warn_delete"), app_commands.Choice(name="Delete Only", value="delete")])
    async def configure_settings(self, interaction: discord.Interaction, default_action: Optional[str] = None):
        if not await self._is_feature_enabled(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild.id)
        settings = self.blocklist_cache.setdefault(guild_id, {}).setdefault("settings", {})
        
        if default_action:
            settings["default_action"] = default_action
            await self.data_manager.save_data("word_blocklist", self.blocklist_cache)
            await interaction.followup.send(f"Default action set to: **{default_action.replace('_', ' ').title()}**")
        else:
            current_action = settings.get("default_action", "warn_delete").replace("_", " ").title()
            embed = discord.Embed(title="Word Blocker Settings", color=discord.Color.blue())
            embed.add_field(name="Default Action", value=current_action, inline=False)
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(WordBlocker(bot))