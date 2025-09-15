# cogs/moderation/auto_reply.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import time
import random
from typing import Optional, Dict, List, Tuple
from collections import defaultdict, deque

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["auto_reply"]
        self.data_manager = self.bot.data_manager
        
        # --- ENHANCED RATE LIMITING ---
        self.GLOBAL_COOLDOWN = 0.3  # Minimum time between any auto-replies
        self.CHANNEL_COOLDOWN = 1.0  # Per-channel cooldown
        self.USER_COOLDOWN = 2.0     # Per-user cooldown to prevent spam
        self.TRIGGER_COOLDOWN = 3.0  # Per-trigger cooldown
        
        # Cooldown tracking
        self.last_global_reply = 0
        self.channel_cooldowns = {}
        self.user_cooldowns = defaultdict(float)
        self.trigger_cooldowns = defaultdict(float)
        
        # --- SMART CACHING ---
        self.all_replies_cache = {}
        self.regex_cache = {}
        # Fixed: Ensure trigger_stats always returns a proper dict
        self.trigger_stats = defaultdict(lambda: {"count": 0, "last_used": 0})
        
        # --- ANTI-SPAM FEATURES ---
        self.recent_messages = defaultdict(lambda: deque(maxlen=10))  # Track recent messages per user
        self.MAX_IDENTICAL_MESSAGES = 3  # Max identical messages before ignoring user
        
        # --- PERFORMANCE METRICS ---
        self.performance_stats = {
            "total_checks": 0,
            "total_replies": 0,
            "cache_hits": 0,
            "regex_misses": 0
        }

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info("Loading optimized auto-replies system...")
        self.all_replies_cache = await self.data_manager.get_data("auto_replies")
        
        # Load enhanced trigger data with better error handling
        try:
            loaded_stats = await self.data_manager.get_data("auto_reply_stats")
            if isinstance(loaded_stats, dict):
                # Convert to defaultdict and ensure all values are proper dicts
                self.trigger_stats = defaultdict(lambda: {"count": 0, "last_used": 0})
                for key, value in loaded_stats.items():
                    if isinstance(value, dict) and "count" in value and "last_used" in value:
                        self.trigger_stats[key] = value
                    else:
                        # Fix corrupted data
                        self.trigger_stats[key] = {"count": 0, "last_used": 0}
            else:
                self.trigger_stats = defaultdict(lambda: {"count": 0, "last_used": 0})
        except Exception as e:
            self.logger.warning(f"Error loading trigger stats, starting fresh: {e}")
            self.trigger_stats = defaultdict(lambda: {"count": 0, "last_used": 0})
        
        # Build regex cache for all guilds
        for guild_id, triggers in self.all_replies_cache.items():
            self._update_regex_for_guild(guild_id, triggers)
            
        self.logger.info(f"Auto-Reply system ready with {len(self.all_replies_cache)} guild configs")

    def _is_spam_message(self, user_id: int, content: str) -> bool:
        """Check if user is sending spam messages."""
        user_history = self.recent_messages[user_id]
        
        # Count identical messages
        identical_count = sum(1 for msg in user_history if msg == content)
        
        if identical_count >= self.MAX_IDENTICAL_MESSAGES:
            return True
            
        # Add current message to history
        user_history.append(content)
        return False

    def _update_regex_for_guild(self, guild_id: str, guild_triggers: dict):
        """Build optimized regex pattern for guild with word boundaries and case insensitivity."""
        if not guild_triggers:
            self.regex_cache[guild_id] = None
            return
            
        all_patterns = []
        
        for trigger, data in guild_triggers.items():
            # Escape the main trigger and add word boundaries
            escaped_trigger = re.escape(trigger)
            all_patterns.append(f"\\b{escaped_trigger}\\b")
            
            # Add alternatives with word boundaries
            for alt in data.get("alts", []):
                escaped_alt = re.escape(alt)
                all_patterns.append(f"\\b{escaped_alt}\\b")
        
        if all_patterns:
            # Create optimized pattern with non-capturing groups
            pattern = "(?:" + "|".join(all_patterns) + ")"
            try:
                self.regex_cache[guild_id] = re.compile(pattern, re.IGNORECASE)
                self.logger.debug(f"Built regex for guild {guild_id} with {len(all_patterns)} patterns")
            except re.error as e:
                self.logger.error(f"Regex compilation failed for guild {guild_id}: {e}")
                self.regex_cache[guild_id] = None
        else:
            self.regex_cache[guild_id] = None

    def _check_all_cooldowns(self, channel_id: int, user_id: int, trigger_key: str) -> Tuple[bool, str]:
        """Check all cooldown types and return (allowed, reason)."""
        now = time.time()
        
        # Global cooldown
        if now - self.last_global_reply < self.GLOBAL_COOLDOWN:
            return False, "global"
            
        # Channel cooldown
        if now - self.channel_cooldowns.get(channel_id, 0) < self.CHANNEL_COOLDOWN:
            return False, "channel"
            
        # User cooldown
        if now - self.user_cooldowns[user_id] < self.USER_COOLDOWN:
            return False, "user"
            
        # Trigger-specific cooldown
        if now - self.trigger_cooldowns[trigger_key] < self.TRIGGER_COOLDOWN:
            return False, "trigger"
            
        return True, ""

    def _update_all_cooldowns(self, channel_id: int, user_id: int, trigger_key: str):
        """Update all cooldown timers."""
        now = time.time()
        self.last_global_reply = now
        self.channel_cooldowns[channel_id] = now
        self.user_cooldowns[user_id] = now
        self.trigger_cooldowns[trigger_key] = now

    def _find_triggered_word(self, content: str, guild_triggers: dict) -> Optional[Tuple[str, dict]]:
        """Find which trigger was activated and return trigger data."""
        content_lower = content.lower()
        
        # Direct lookup first (fastest)
        for main_trigger, data in guild_triggers.items():
            if main_trigger in content_lower:
                # Verify word boundary
                pattern = f"\\b{re.escape(main_trigger)}\\b"
                if re.search(pattern, content_lower):
                    return main_trigger, data
                    
        # Check alternatives
        for main_trigger, data in guild_triggers.items():
            for alt in data.get("alts", []):
                if alt.lower() in content_lower:
                    pattern = f"\\b{re.escape(alt.lower())}\\b"
                    if re.search(pattern, content_lower):
                        return main_trigger, data
                        
        return None

    def _safe_update_stats(self, guild_id: str, main_trigger: str):
        """Safely update trigger statistics with proper error handling."""
        try:
            stats_key = f"{guild_id}:{main_trigger}"
            
            # Ensure the stats entry exists and is properly formatted
            if stats_key not in self.trigger_stats:
                self.trigger_stats[stats_key] = {"count": 0, "last_used": 0}
            
            # Verify the stats entry is a proper dict
            current_stats = self.trigger_stats[stats_key]
            if not isinstance(current_stats, dict):
                self.logger.warning(f"Corrupted stats for {stats_key}, resetting")
                self.trigger_stats[stats_key] = {"count": 0, "last_used": 0}
                current_stats = self.trigger_stats[stats_key]
            
            # Safely update stats
            if "count" not in current_stats:
                current_stats["count"] = 0
            if "last_used" not in current_stats:
                current_stats["last_used"] = 0
                
            current_stats["count"] += 1
            current_stats["last_used"] = time.time()
            
            self.logger.debug(f"Updated stats for {stats_key}: {current_stats}")
            
        except Exception as e:
            self.logger.error(f"Error updating stats for {guild_id}:{main_trigger}: {e}")
            # Don't let stats errors break the auto-reply functionality

    async def check_for_reply(self, message: discord.Message) -> bool:
        """Ultra-fast message check with comprehensive rate limiting and anti-spam."""
        self.performance_stats["total_checks"] += 1
        
        if not message.guild:
            return False
            
        # Anti-spam check
        if self._is_spam_message(message.author.id, message.content):
            return False
            
        guild_id = str(message.guild.id)
        guild_regex = self.regex_cache.get(guild_id)
        
        if not guild_regex:
            self.performance_stats["regex_misses"] += 1
            return False
            
        # Quick regex check first
        if not guild_regex.search(message.content):
            return False
            
        self.performance_stats["cache_hits"] += 1
        
        # Find exact trigger
        guild_triggers = self.all_replies_cache.get(guild_id, {})
        trigger_result = self._find_triggered_word(message.content, guild_triggers)
        
        if not trigger_result:
            return False
            
        main_trigger, trigger_data = trigger_result
        
        # Check all cooldowns
        allowed, cooldown_type = self._check_all_cooldowns(
            message.channel.id, 
            message.author.id, 
            main_trigger
        )
        
        if not allowed:
            self.logger.debug(f"Auto-reply blocked by {cooldown_type} cooldown")
            return False
            
        try:
            # Update cooldowns first
            self._update_all_cooldowns(message.channel.id, message.author.id, main_trigger)
            
            # Get reply content with variable support
            reply_content = await self._process_reply_content(trigger_data["reply"], message)
            
            # Send reply
            await message.reply(reply_content, mention_author=False)
            
            # Update statistics safely
            self.performance_stats["total_replies"] += 1
            self._safe_update_stats(guild_id, main_trigger)
            
            # Save stats periodically (with error handling)
            if self.performance_stats["total_replies"] % 10 == 0:
                try:
                    # Convert defaultdict to regular dict for saving
                    stats_to_save = dict(self.trigger_stats)
                    await self.data_manager.save_data("auto_reply_stats", stats_to_save)
                except Exception as e:
                    self.logger.error(f"Error saving stats: {e}")
                
            self.logger.info(f"Auto-reply triggered: '{main_trigger}' in {message.guild.name}")
            return True
            
        except discord.Forbidden:
            self.logger.warning(f"Missing permissions to reply in {message.guild.name}#{message.channel.name}")
        except discord.HTTPException as e:
            self.logger.error(f"Failed to send auto-reply: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in auto-reply: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            
        return False

    async def _process_reply_content(self, reply_template: str, message: discord.Message) -> str:
        """Process reply content with variable substitution and multiple reply support."""
        try:
            # Handle multiple replies (separated by |)
            if "|" in reply_template:
                replies = [r.strip() for r in reply_template.split("|") if r.strip()]
                if replies:
                    reply_template = random.choice(replies)
                else:
                    reply_template = "Hello!"  # Fallback
            
            # Variable substitution with safe handling
            variables = {
                "{user}": getattr(message.author, 'display_name', 'Unknown User'),
                "{mention}": getattr(message.author, 'mention', '@Unknown'),
                "{server}": getattr(message.guild, 'name', 'Unknown Server') if message.guild else 'DM',
                "{channel}": getattr(message.channel, 'name', 'unknown-channel'),
            }
            
            processed_reply = reply_template
            for var, value in variables.items():
                try:
                    processed_reply = processed_reply.replace(var, str(value))
                except Exception as e:
                    self.logger.warning(f"Error replacing variable {var}: {e}")
                    # Continue with other variables
                    
            # Ensure the reply isn't empty and isn't too long
            if not processed_reply.strip():
                processed_reply = "Hello!"
            elif len(processed_reply) > 2000:
                processed_reply = processed_reply[:1997] + "..."
                
            return processed_reply
            
        except Exception as e:
            self.logger.error(f"Error processing reply template '{reply_template}': {e}")
            return "Hello!"  # Safe fallback

    # --- ENHANCED COMMANDS ---

    @app_commands.command(name="autoreply", description="Add or remove an auto-reply trigger with advanced options.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        action="Add a new trigger or remove an existing one.",
        trigger="The word/phrase to listen for.",
        reply="The reply text. Use | to separate multiple random replies. Use {user}, {mention}, {server}, {channel} for variables."
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove")
    ])
    async def manage_autoreply(self, interaction: discord.Interaction, action: str, trigger: str, reply: Optional[str] = None):
        await interaction.response.defer()
        
        if action == "add" and not reply:
            return await interaction.followup.send(
                "You must provide a `reply` when adding a trigger. Obviously.", 
                ephemeral=True
            )
            
        guild_id = str(interaction.guild_id)
        guild_triggers = self.all_replies_cache.setdefault(guild_id, {})
        trigger_key = trigger.lower().strip()
        
        if action == "add":
            if trigger_key in guild_triggers:
                return await interaction.followup.send(
                    self.personality["already_exists"], 
                    ephemeral=True
                )
                
            # Validate reply content
            if len(reply) > 2000:
                return await interaction.followup.send(
                    "That reply is too long. Keep it under 2000 characters.", 
                    ephemeral=True
                )
                
            guild_triggers[trigger_key] = {
                "reply": reply,
                "alts": [],
                "created_by": interaction.user.id,
                "created_at": int(time.time())
            }
            
            response_msg = self.personality["trigger_set"].format(trigger=f"`{trigger}`")
            
            # Show variable info if used
            if any(var in reply for var in ["{user}", "{mention}", "{server}", "{channel}"]):
                response_msg += "\n*I noticed you used variables. Good choice.*"
                
            if "|" in reply:
                reply_count = len([r.strip() for r in reply.split("|")])
                response_msg += f"\n*I'll randomly choose from {reply_count} different replies.*"
                
        elif action == "remove":
            if trigger_key not in guild_triggers:
                return await interaction.followup.send(
                    self.personality["trigger_not_found"], 
                    ephemeral=True
                )
                
            del guild_triggers[trigger_key]
            response_msg = self.personality["trigger_removed"].format(trigger=f"`{trigger}`")
            
            # Clean up empty guild data
            if not guild_triggers:
                del self.all_replies_cache[guild_id]
        
        # Save and update cache
        await self.data_manager.save_data("auto_replies", self.all_replies_cache)
        self._update_regex_for_guild(guild_id, guild_triggers)
        
        await interaction.followup.send(response_msg)

    @app_commands.command(name="autoreply-alt", description="Add multiple alternative words to an existing trigger.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        main_trigger="The trigger to add alternatives for.",
        alternatives="The new alternative words, separated by spaces."
    )
    async def add_alts_bulk(self, interaction: discord.Interaction, main_trigger: str, alternatives: str):
        await interaction.response.defer()
        
        guild_id = str(interaction.guild_id)
        guild_triggers = self.all_replies_cache.get(guild_id, {})
        main_key = main_trigger.lower().strip()
        
        if main_key not in guild_triggers:
            return await interaction.followup.send(
                self.personality["trigger_not_found"], 
                ephemeral=True
            )
            
        alts_to_add = [alt.strip().lower() for alt in alternatives.split() if alt.strip()]
        
        if not alts_to_add:
            return await interaction.followup.send(
                self.personality["error_empty"], 
                ephemeral=True
            )
            
        existing_alts_set = set(guild_triggers[main_key].setdefault("alts", []))
        actually_added = [alt for alt in alts_to_add 
                         if alt not in existing_alts_set and alt != main_key]
        
        if not actually_added:
            return await interaction.followup.send(
                self.personality["already_exists"], 
                ephemeral=True
            )
            
        existing_alts_set.update(actually_added)
        guild_triggers[main_key]["alts"] = sorted(list(existing_alts_set))
        
        await self.data_manager.save_data("auto_replies", self.all_replies_cache)
        self._update_regex_for_guild(guild_id, guild_triggers)
        
        await interaction.followup.send(
            f"Okay, I've added `{', '.join(actually_added)}` as alternatives for `{main_trigger}`."
        )

    @app_commands.command(name="autoreply-list", description="List all configured auto-replies with detailed information.")
    async def list_replies(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        guild_triggers = self.all_replies_cache.get(guild_id, {})
        
        if not guild_triggers:
            return await interaction.followup.send(self.personality["list_empty"])
            
        embed = discord.Embed(
            title="Server Auto-Replies", 
            color=discord.Color.blue(),
            description=f"Total triggers: {len(guild_triggers)}"
        )
        
        for trigger, data in sorted(guild_triggers.items()):
            reply_preview = data["reply"]
            if len(reply_preview) > 100:
                reply_preview = reply_preview[:97] + "..."
                
            field_value = f"**Reply:** {reply_preview}"
            
            if data.get("alts"):
                field_value += f"\n**Alternatives:** `{'`, `'.join(data['alts'])}`"
                
            # Show stats if available
            stats_key = f"{guild_id}:{trigger}"
            if stats_key in self.trigger_stats:
                stats = self.trigger_stats[stats_key]
                field_value += f"\n**Uses:** {stats['count']}"
                
            embed.add_field(
                name=f"`{trigger}`",
                value=field_value,
                inline=False
            )
            
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="autoreply-stats", description="View auto-reply performance statistics.")
    @is_bot_admin()
    async def view_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        embed = discord.Embed(
            title="Auto-Reply Performance Stats",
            color=discord.Color.green()
        )
        
        # Global stats
        stats = self.performance_stats
        embed.add_field(
            name="Global Performance",
            value=f"**Total Checks:** {stats['total_checks']:,}\n"
                  f"**Total Replies:** {stats['total_replies']:,}\n"
                  f"**Cache Hit Rate:** {(stats['cache_hits']/max(stats['total_checks'], 1)*100):.1f}%\n"
                  f"**Active Guilds:** {len(self.all_replies_cache)}",
            inline=False
        )
        
        # Guild-specific stats
        guild_id = str(interaction.guild.id)
        guild_stats = {k: v for k, v in self.trigger_stats.items() 
                      if k.startswith(f"{guild_id}:")}
        
        if guild_stats:
            top_triggers = sorted(guild_stats.items(), 
                                key=lambda x: x[1]["count"], 
                                reverse=True)[:5]
            
            top_list = []
            for key, data in top_triggers:
                trigger_name = key.split(":", 1)[1]
                top_list.append(f"`{trigger_name}`: {data['count']} uses")
                
            embed.add_field(
                name="Top Triggers (This Server)",
                value="\n".join(top_list) or "No usage data yet",
                inline=False
            )
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="autoreply-test", description="Test if a message would trigger an auto-reply.")
    @is_bot_admin()
    @app_commands.describe(test_message="The message content to test.")
    async def test_trigger(self, interaction: discord.Interaction, test_message: str):
        await interaction.response.defer(ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        guild_regex = self.regex_cache.get(guild_id)
        
        if not guild_regex:
            return await interaction.followup.send(
                "No auto-replies are configured for this server."
            )
            
        if not guild_regex.search(test_message):
            return await interaction.followup.send(
                f"No triggers found in: `{test_message}`"
            )
            
        guild_triggers = self.all_replies_cache.get(guild_id, {})
        trigger_result = self._find_triggered_word(test_message, guild_triggers)
        
        if not trigger_result:
            return await interaction.followup.send(
                "Regex matched but no specific trigger found. This shouldn't happen."
            )
            
        main_trigger, trigger_data = trigger_result
        processed_reply = await self._process_reply_content(
            trigger_data["reply"], 
            interaction.message if hasattr(interaction, 'message') 
            else type('obj', (object,), {
                'author': interaction.user,
                'guild': interaction.guild,
                'channel': interaction.channel
            })()
        )
        
        embed = discord.Embed(
            title="Auto-Reply Test Result",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Triggered Word",
            value=f"`{main_trigger}`",
            inline=True
        )
        
        embed.add_field(
            name="Would Reply With",
            value=processed_reply[:1024],  # Discord embed field limit
            inline=False
        )
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AutoReply(bot))