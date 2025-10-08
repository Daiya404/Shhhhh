# cogs/utility/reminders.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import re
import time
import uuid
import asyncio
import bisect
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

class Reminders(commands.Cog):
    # Pre-compile regex for a small performance boost
    TIME_PATTERN = re.compile(r"(\d+)\s*(d|w|h|m|s|day|week|hour|minute|second)s?", re.IGNORECASE)

    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["reminders"]
        self.data_manager = self.bot.data_manager

        # --- OPTIMIZATIONS ---
        self.reminders_cache: List[Dict] = []
        self.user_settings_cache: Dict = {}
        
        # Event-driven system for the main loop
        self._loop_wakeup_event = asyncio.Event()
        
        # Background saving mechanism
        self._is_dirty = asyncio.Event()
        self._save_lock = asyncio.Lock()
        
        self.main_task: Optional[asyncio.Task] = None
        self.save_task: Optional[asyncio.Task] = None

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """A local check to see if the reminders feature is enabled."""
        feature_manager = self.bot.get_cog("FeatureManager")
        # The feature name here MUST match the one in AVAILABLE_FEATURES
        feature_name = "reminders" 
        
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, feature_name):
            # This personality response is just a suggestion; you can create a generic one.
            await interaction.response.send_message(f"Hmph. The {feature_name.replace('_', ' ').title()} feature is disabled on this server.", ephemeral=True)
            return False
        return True

    # --- COG LIFECYCLE (SETUP & SHUTDOWN) ---
    async def cog_load(self):
        """Called when the cog is loaded. Loads data and starts background tasks."""
        self.logger.info("Loading reminders into memory...")
        self.reminders_cache = await self.data_manager.get_data("reminders") or []
        # Ensure the cache is sorted by due time for efficient processing
        self.reminders_cache.sort(key=lambda r: r.get("due_timestamp", 0))
        
        self.user_settings_cache = await self.data_manager.get_data("user_settings")
        self.logger.info(f"Loaded {len(self.reminders_cache)} reminders.")

        self.main_task = self.bot.loop.create_task(self.check_reminders_loop())
        self.save_task = self.bot.loop.create_task(self._periodic_save())

    async def cog_unload(self):
        """Called on shutdown. Cancels tasks and performs a final save."""
        if self.main_task: self.main_task.cancel()
        if self.save_task: self.save_task.cancel()
        
        if self._is_dirty.is_set():
            self.logger.info("Performing final save for reminders...")
            await self.data_manager.save_data("reminders", self.reminders_cache)
            self.logger.info("Final save complete.")

    async def _periodic_save(self):
        """A background task that saves data to disk only when it has changed."""
        while not self.bot.is_closed():
            try:
                await self._is_dirty.wait()
                await asyncio.sleep(60) # Wait a minute to batch multiple changes
                async with self._save_lock:
                    await self.data_manager.save_data("reminders", self.reminders_cache)
                    self._is_dirty.clear()
                    self.logger.info("Periodically saved reminders data.")
            except asyncio.CancelledError: break
            except Exception as e:
                self.logger.error(f"Error in reminders periodic save task: {e}", exc_info=True)
                await asyncio.sleep(120)

    # --- CORE REMINDER LOOP ---
    async def check_reminders_loop(self):
        """Highly efficient, event-driven loop that only wakes when necessary."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                self._loop_wakeup_event.clear()
                
                if not self.reminders_cache:
                    await self._loop_wakeup_event.wait()
                    continue

                next_reminder_time = self.reminders_cache[0].get("due_timestamp", 0)
                now = datetime.now(timezone.utc).timestamp()
                sleep_for = next_reminder_time - now
                
                if sleep_for > 0:
                    await asyncio.wait_for(self._loop_wakeup_event.wait(), timeout=sleep_for)
                
                now = datetime.now(timezone.utc).timestamp()
                due_reminders = []
                while self.reminders_cache and self.reminders_cache[0].get("due_timestamp", 0) <= now:
                    due_reminders.append(self.reminders_cache.pop(0))
                
                if due_reminders:
                    for item in due_reminders:
                        await self._send_notification(item)
                        if item.get("repeat_interval"):
                            if next_item := self._create_next_occurrence(item):
                                self._add_reminder(next_item)
                    self._is_dirty.set()

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in check_reminders_loop: {e}", exc_info=True)
                await asyncio.sleep(30)

    # --- COMMANDS ---
    @app_commands.command(name="remind", description="Manage your reminders.")
    @app_commands.describe(action="What you want to do.", when="When to remind you (e.g., '1d 12h', 'tomorrow').", message="What to remind you about.", reminder_id="The ID of the reminder to delete.", repeat="Set a repeating interval.")
    @app_commands.choices(action=[app_commands.Choice(name="Set", value="set"), app_commands.Choice(name="List", value="list"), app_commands.Choice(name="Delete", value="delete")], repeat=[app_commands.Choice(name="Daily", value="daily"), app_commands.Choice(name="Weekly", value="weekly"), app_commands.Choice(name="Monthly", value="monthly")])
    async def manage_reminders(self, interaction: discord.Interaction, action: str, when: Optional[str] = None, message: Optional[str] = None, reminder_id: Optional[str] = None, repeat: Optional[app_commands.Choice[str]] = None):
        if not await self._is_feature_enabled(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        if action == "set":
            if not when or not message: return await interaction.followup.send("You need `when` and `message` to set a reminder.")
            delta = self._parse_time(when)
            if delta is None or delta.total_seconds() <= 0: return await interaction.followup.send(self.personality["invalid_time"])

            due_time = datetime.now(timezone.utc) + delta
            new_item = {"id": str(uuid.uuid4())[:8], "user_id": interaction.user.id, "channel_id": interaction.channel_id, "guild_id": interaction.guild_id, "due_timestamp": int(due_time.timestamp()), "created_timestamp": int(time.time()), "message": message, "repeat_interval": repeat.value if repeat else None}
            
            self._add_reminder(new_item)
            
            response = self.personality["reminder_set"].format(id=f'`{new_item["id"]}`')
            await interaction.followup.send(f"{response} I'll notify you at <t:{new_item['due_timestamp']}:F>.")

        elif action == "list":
            user_items = [r for r in self.reminders_cache if r.get("user_id") == interaction.user.id]
            if not user_items: return await interaction.followup.send(self.personality["list_empty"])
            
            embed = discord.Embed(title=self.personality["list_title"], color=discord.Color.blue())
            description = [f"**ID:** `{r['id']}` - <t:{r['due_timestamp']}:R>{' (Repeats ' + r['repeat_interval'] + ')' if r.get('repeat_interval') else ''}\n> {r['message'][:40]}{'...' if len(r['message']) > 40 else ''}" for r in user_items]
            embed.description = "\n".join(description)
            await interaction.followup.send(embed=embed)

        elif action == "delete":
            if not reminder_id: return await interaction.followup.send("You need to provide a `reminder_id` to delete.")
            if not self._remove_reminder(reminder_id, interaction.user.id):
                return await interaction.followup.send(self.personality["delete_not_found"])
            await interaction.followup.send(self.personality["deleted"])

    @manage_reminders.autocomplete("reminder_id")
    async def reminder_id_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        user_items = [r for r in self.reminders_cache if r.get("user_id") == interaction.user.id]
        choices = [app_commands.Choice(name=f"ID: {r['id']} | {r['message'][:50]}", value=r['id']) for r in user_items if current.lower() in r['id'].lower() or current.lower() in r['message'].lower()]
        return choices[:25]

    @app_commands.command(name="remind-settings", description="Choose where your reminders are sent.")
    @app_commands.describe(location="DM (private) or the original channel (public).")
    @app_commands.choices(location=[app_commands.Choice(name="Direct Message (DM)", value="dm"), app_commands.Choice(name="Original Channel", value="channel")])
    async def set_delivery(self, interaction: discord.Interaction, location: app_commands.Choice[str]):
        if not await self._is_feature_enabled(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        user_settings = self.user_settings_cache.setdefault(str(interaction.guild_id), {}).setdefault(str(interaction.user.id), {})
        user_settings["remind_in_channel"] = (location.value == "channel")
        await self.data_manager.save_data("user_settings", self.user_settings_cache)
        await interaction.followup.send(self.personality["delivery_channel"] if user_settings["remind_in_channel"] else self.personality["delivery_dm"])

    @app_commands.command(name="remind-admin-delete", description="[Admin] Forcibly delete any user's reminder by its ID.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    async def admin_delete(self, interaction: discord.Interaction, reminder_id: str):
        if not await self._is_feature_enabled(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if self._remove_reminder(reminder_id):
            await interaction.followup.send(self.personality["admin_deleted"])
        else:
            await interaction.followup.send(self.personality["delete_not_found"])

    # --- Helper Functions ---
    def _add_reminder(self, item: Dict):
        """Efficiently adds a reminder to the sorted cache and signals the loop."""
        timestamps = [r['due_timestamp'] for r in self.reminders_cache]
        index = bisect.bisect_left(timestamps, item['due_timestamp'])
        self.reminders_cache.insert(index, item)
        self._is_dirty.set()
        if index == 0:
            self._loop_wakeup_event.set()

    def _remove_reminder(self, reminder_id: str, user_id: Optional[int] = None) -> bool:
        """Removes a reminder from the cache. Returns True if successful."""
        for i, r in enumerate(self.reminders_cache):
            if r.get("id") == reminder_id:
                if user_id and r.get("user_id") != user_id: return False
                self.reminders_cache.pop(i)
                self._is_dirty.set()
                if i == 0: self._loop_wakeup_event.set()
                return True
        return False

    async def _send_notification(self, item: dict):
        user = self.bot.get_user(item["user_id"])
        if not user: return

        embed = discord.Embed(title=self.personality["reminder_dm_title"], description=item["message"], color=discord.Color.blue(), timestamp=datetime.fromtimestamp(item["created_timestamp"], tz=timezone.utc))
        should_notify_in_channel = self.user_settings_cache.get(str(item["guild_id"]), {}).get(str(user.id), {}).get("remind_in_channel", False)
        
        channel = self.bot.get_channel(item["channel_id"]) if should_notify_in_channel else None
        if channel:
            embed.title = self.personality["reminder_channel_title"].format(user=user.display_name)
            try: await channel.send(user.mention, embed=embed)
            except discord.Forbidden: await user.send(embed=embed)
        else:
            try: await user.send(embed=embed)
            except discord.Forbidden:
                fallback_channel = self.bot.get_channel(item["channel_id"])
                if fallback_channel: await fallback_channel.send(self.personality["reminder_channel_ping"].format(user=user.mention), embed=embed)

    def _create_next_occurrence(self, old: dict) -> Optional[dict]:
        interval, now = old.get("repeat_interval"), datetime.now(timezone.utc)
        delta = None
        if interval == "daily": delta = timedelta(days=1)
        elif interval == "weekly": delta = timedelta(weeks=1)
        elif interval == "monthly": delta = timedelta(days=30)
        if not delta: return None
        new = old.copy(); new["due_timestamp"] = int((now + delta).timestamp()); return new

    def _parse_time(self, time_str: str) -> Optional[timedelta]:
        if time_str.lower().strip() == "tomorrow": return timedelta(days=1)
        total_seconds = 0
        units = {'d': 86400, 'w': 604800, 'h': 3600, 'm': 60, 's': 1}
        for value, unit in self.TIME_PATTERN.findall(time_str):
            total_seconds += int(value) * units[unit[0].lower()]
        return timedelta(seconds=total_seconds) if total_seconds > 0 else None

async def setup(bot):
    await bot.add_cog(Reminders(bot))