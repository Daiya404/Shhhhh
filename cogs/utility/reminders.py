# cogs/utility/reminders.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["reminders"]
        self.data_manager = self.bot.data_manager

        # --- OPTIMIZATION: In-memory caches ---
        self.reminders_cache: List[dict] = []
        self.user_settings_cache: dict = {}
        
        self.check_reminders.start()

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """A local check to see if the reminders feature is enabled."""
        feature_manager = self.bot.get_cog("FeatureManager")
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, "reminders"):
            await interaction.response.send_message("Hmph. The Custom Roles feature is disabled on this server.", ephemeral=True)
            return False
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        """Loads all reminder data into the caches when the cog is ready."""
        self.logger.info("Loading all reminders into memory...")
        reminders_data = await self.data_manager.get_data("reminders")
        self.reminders_cache = reminders_data if isinstance(reminders_data, list) else []
        
        self.user_settings_cache = await self.data_manager.get_data("user_settings")
        self.logger.info(f"Loaded {len(self.reminders_cache)} reminders into cache.")

    def cog_unload(self):
        self.check_reminders.cancel()

    @tasks.loop(seconds=15)
    async def check_reminders(self):
        """Optimized loop that operates only on the in-memory cache."""
        now = datetime.now(timezone.utc).timestamp()
        due = [r for r in self.reminders_cache if r.get("due_timestamp", 0) <= now]
        if not due:
            return
            
        still_active = [r for r in self.reminders_cache if r.get("due_timestamp", 0) > now]
        
        for item in due:
            await self._send_notification(item)
            if item.get("repeat_interval"):
                if next_item := self._create_next_occurrence(item):
                    still_active.append(next_item)
        
        # If the list has changed, update the cache and save to disk
        if len(still_active) != len(self.reminders_cache):
            self.reminders_cache = still_active
            await self.data_manager.save_data("reminders", self.reminders_cache)

    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()

    # --- NEW COMMAND ---
    @app_commands.command(name="remind", description="Manage your reminders.")
    @app_commands.describe(
        action="What you want to do.",
        when="When to remind you (e.g., '1d 12h', 'tomorrow'). Needed for 'set'.",
        message="What to remind you about. Needed for 'set'.",
        reminder_id="The ID of the reminder to delete. Needed for 'delete'.",
        repeat="Set a repeating interval for 'set'."
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Set", value="set"),
        app_commands.Choice(name="List", value="list"),
        app_commands.Choice(name="Delete", value="delete"),
    ])
    @app_commands.choices(repeat=[
        app_commands.Choice(name="Daily", value="daily"),
        app_commands.Choice(name="Weekly", value="weekly"),
        app_commands.Choice(name="Monthly", value="monthly")
    ])
    async def manage_reminders(self, interaction: discord.Interaction, action: str, when: Optional[str] = None, message: Optional[str] = None, reminder_id: Optional[str] = None, repeat: Optional[app_commands.Choice[str]] = None):
        if not await self._is_feature_enabled(interaction): return
        await interaction.response.defer(ephemeral=True)

        # --- SET LOGIC ---
        if action == "set":
            if not when or not message:
                return await interaction.followup.send("You need to provide `when` and `message` to set a reminder.")
            
            delta = self._parse_time(when)
            if delta is None or delta.total_seconds() <= 0:
                return await interaction.followup.send(self.personality["invalid_time"])

            now, due_time = datetime.now(timezone.utc), datetime.now(timezone.utc) + delta
            item_id = str(uuid.uuid4())[:8]
            
            new_item = { "id": item_id, "user_id": interaction.user.id, "channel_id": interaction.channel_id, "guild_id": interaction.guild_id, "due_timestamp": int(due_time.timestamp()), "created_timestamp": int(now.timestamp()), "message": message, "repeat_interval": repeat.value if repeat else None }
            
            self.reminders_cache.append(new_item)
            await self.data_manager.save_data("reminders", self.reminders_cache)
            
            response = self.personality["reminder_set"].format(id=f'`{item_id}`')
            await interaction.followup.send(f"{response} I'll notify you at <t:{new_item['due_timestamp']}:F>.")

        # --- LIST LOGIC ---
        elif action == "list":
            user_items = [r for r in self.reminders_cache if r.get("user_id") == interaction.user.id]
            if not user_items:
                return await interaction.followup.send(self.personality["list_empty"])
            
            embed = discord.Embed(title=self.personality["list_title"], color=discord.Color.blue())
            description = [f"**ID:** `{r['id']}` - <t:{r['due_timestamp']}:R>{' (Repeats ' + r['repeat_interval'] + ')' if r.get('repeat_interval') else ''}\n> {r['message'][:40]}{'...' if len(r['message']) > 40 else ''}" for r in sorted(user_items, key=lambda x: x["due_timestamp"])]
            embed.description = "\n".join(description)
            await interaction.followup.send(embed=embed)

        # --- DELETE LOGIC ---
        elif action == "delete":
            if not reminder_id:
                return await interaction.followup.send("You need to provide a `reminder_id` to delete.")
            
            item_to_delete = next((r for r in self.reminders_cache if r.get("id") == reminder_id), None)
            
            if not item_to_delete:
                return await interaction.followup.send(self.personality["delete_not_found"])
            if item_to_delete.get("user_id") != interaction.user.id:
                return await interaction.followup.send(self.personality["delete_not_yours"])

            self.reminders_cache.remove(item_to_delete)
            await self.data_manager.save_data("reminders", self.reminders_cache)
            await interaction.followup.send(self.personality["deleted"])

    @manage_reminders.autocomplete("reminder_id")
    async def reminder_id_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        user_items = [r for r in self.reminders_cache if r.get("user_id") == interaction.user.id]
        choices = [app_commands.Choice(name=f"ID: {r['id']} | {r['message'][:50]}{'...' if len(r['message']) > 50 else ''}", value=r['id']) for r in user_items if current.lower() in r['id'].lower() or current.lower() in r['message'].lower()]
        return choices[:25]

    # --- Settings and Admin Commands ---
    @app_commands.command(name="remind-settings", description="Choose where your reminders are sent.")
    @app_commands.describe(location="DM (private) or the original channel (public).")
    @app_commands.choices(location=[app_commands.Choice(name="Direct Message (DM)", value="dm"), app_commands.Choice(name="Original Channel", value="channel")])
    async def set_delivery(self, interaction: discord.Interaction, location: app_commands.Choice[str]):
        if not await self._is_feature_enabled(interaction): return
        await interaction.response.defer(ephemeral=True)
        guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
        remind_in_channel = (location.value == "channel")
        
        self.user_settings_cache.setdefault(guild_id, {}).setdefault(user_id, {})["remind_in_channel"] = remind_in_channel
        await self.data_manager.save_data("user_settings", self.user_settings_cache)
        
        await interaction.followup.send(self.personality["delivery_channel"] if remind_in_channel else self.personality["delivery_dm"])

    @app_commands.command(name="remind-admin-delete", description="[Admin] Forcibly delete any user's reminder by its ID.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(reminder_id="The full ID of the reminder to delete.")
    @is_bot_admin()
    async def admin_delete(self, interaction: discord.Interaction, reminder_id: str):
        if not await self._is_feature_enabled(interaction): return
        await interaction.response.defer(ephemeral=True)
        item_to_delete = next((r for r in self.reminders_cache if r.get("id") == reminder_id), None)
        if not item_to_delete:
            return await interaction.followup.send(self.personality["delete_not_found"])
        
        self.reminders_cache.remove(item_to_delete)
        await self.data_manager.save_data("reminders", self.reminders_cache)
        await interaction.followup.send(self.personality["admin_deleted"])

    # --- Helper Functions ---
    async def _send_notification(self, item: dict):
        user = self.bot.get_user(item["user_id"])
        if not user: return

        channel = self.bot.get_channel(item["channel_id"])
        channel_name = channel.name if channel else 'an unknown channel'
        
        embed = discord.Embed(
            title=self.personality["reminder_dm_title"],
            description=item["message"], color=discord.Color.blue(),
            timestamp=datetime.fromtimestamp(item["created_timestamp"], tz=timezone.utc)
        )
        embed.set_footer(text=f"Set in: #{channel_name}")

        # Read from the user settings cache for speed
        should_notify_in_channel = self.user_settings_cache.get(str(item["guild_id"]), {}).get(str(user.id), {}).get("remind_in_channel", False)

        if should_notify_in_channel and channel:
            embed.title = self.personality["reminder_channel_title"].format(user=user.display_name)
            try: await channel.send(user.mention, embed=embed)
            except discord.Forbidden: pass
        else:
            try: await user.send(embed=embed)
            except discord.Forbidden:
                if channel: # Fallback to channel
                    await channel.send(self.personality["reminder_channel_ping"].format(user=user.mention), embed=embed)

    def _create_next_occurrence(self, old_reminder: dict) -> Optional[dict]:
        interval, now = old_reminder.get("repeat_interval"), datetime.now(timezone.utc)
        delta = None
        if interval == "daily": delta = timedelta(days=1)
        elif interval == "weekly": delta = timedelta(weeks=1)
        elif interval == "monthly": delta = timedelta(days=30)
        else: return None
        new_reminder = old_reminder.copy()
        new_reminder["due_timestamp"] = int((now + delta).timestamp())
        return new_reminder

    def _parse_time(self, time_str: str) -> Optional[timedelta]:
        time_str = time_str.lower().strip()
        if time_str == "tomorrow": return timedelta(days=1)
        total_seconds = 0
        units = {'d': 86400, 'w': 604800, 'h': 3600, 'm': 60, 's': 1}
        pattern = re.compile(r"(\d+)\s*(d|w|h|m|s|day|week|hour|minute|second)s?")
        matches = pattern.findall(time_str)
        if not matches: return None
        for value, unit in matches:
            total_seconds += int(value) * units[unit[0]]
        return timedelta(seconds=total_seconds) if total_seconds > 0 else None

async def setup(bot):
    await bot.add_cog(Reminders(bot))