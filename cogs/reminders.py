import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
from pathlib import Path
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .bot_admin import BotAdmin

# Personality Responses for this Cog
PERSONALITY = {
    "reminder_set": "Fine, I'll remember that for you. It's not like I have anything better to do. Your reminder ID is `{id}`.",
    "timer_set": "Okay, timer set for `{duration}`. I'll let you know when it's done.",
    "reminder_dm_title": "Hey. You told me to remind you about this.",
    "timer_dm_title": "Time's up!",
    "reminder_channel_ping": "{user}, I tried to DM you, but you've got them blocked. You told me to remind you about this.",
    "reminder_channel_title": "A reminder for {user}!",
    "list_empty": "You have no active {type}s.",
    "list_title": "Your Active {type}s",
    "deleted": "Okay, I've forgotten about that {type}.",
    "admin_deleted": "Done. I have deleted that reminder.",
    "delete_not_found": "I can't find a {type} with that ID. Are you sure you typed it correctly?",
    "delete_not_yours": "That's not your {type} to delete. Mind your own business.",
    "invalid_time": "That doesn't look like a real time format. Use something like `1d`, `2h30m`, `tomorrow`, or `1 week`.",
    "delivery_dm": "Okay, I'll send your reminders and timers via **Direct Message** from now on.",
    "delivery_channel": "Got it. I'll send your reminders and timers publicly in the **Original Channel** from now on."
}

class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.reminders_file = Path("data/reminders.json")
        self.settings_file = Path("data/user_settings.json")
        self.reminders: List[Dict] = self._load_json(self.reminders_file)
        self.user_settings: Dict[str, Dict] = self._load_json(self.settings_file)
        self.check_reminders.start()

    def cog_unload(self): self.check_reminders.cancel()
    def _load_json(self, file_path: Path) -> Dict:
        if not file_path.exists(): return {} if "user_settings" in str(file_path) else []
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError):
            self.logger.error(f"Error loading {file_path}", exc_info=True)
            return {} if "user_settings" in str(file_path) else []
    async def _save_json(self, data, file_path: Path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except IOError:
            self.logger.error(f"Error saving {file_path}", exc_info=True)

    @tasks.loop(seconds=15)
    async def check_reminders(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc).timestamp()
        due = [r for r in self.reminders if r.get("due_timestamp", 0) <= now]
        if not due: return
        still_active = [r for r in self.reminders if r.get("due_timestamp", 0) > now]
        for item in due:
            await self._send_notification(item)
            if item.get("type") == "reminder" and item.get("repeat_interval"):
                if next_item := self._create_next_occurrence(item):
                    still_active.append(next_item)
        self.reminders = still_active
        await self._save_json(self.reminders, self.reminders_file)

    # Command Groups
    remind_group = app_commands.Group(name="remind", description="Set, view, or delete personal reminders.")
    timer_group = app_commands.Group(name="timer", description="Set, view, or cancel personal timers.")
    settings_group = app_commands.Group(name="settings", parent=remind_group, description="Manage your personal reminder settings.")
    admin_group = app_commands.Group(name="remind-admin", description="Admin commands for managing reminders.")

    # Reminder Commands
    @remind_group.command(name="set", description="Set a reminder for the future.")
    @app_commands.describe(when="When to remind you (e.g., 1d 12h, tomorrow).", message="What to remind you about.", repeat="Set a repeating interval.")
    @app_commands.choices(repeat=[app_commands.Choice(name="Daily", value="daily"), app_commands.Choice(name="Weekly", value="weekly"), app_commands.Choice(name="Monthly", value="monthly")])
    async def set_reminder(self, interaction: discord.Interaction, when: str, message: str, repeat: Optional[app_commands.Choice[str]] = None):
        await self._create_item(interaction, "reminder", when, message, repeat)

    @remind_group.command(name="list", description="List your active reminders.")
    async def list_reminders(self, interaction: discord.Interaction):
        await self._list_items(interaction, "reminder")

    @remind_group.command(name="delete", description="Delete an active reminder using its ID.")
    @app_commands.describe(reminder_id="The ID of the reminder you want to delete.")
    async def delete_reminder(self, interaction: discord.Interaction, reminder_id: str):
        await self._delete_item(interaction, "reminder", reminder_id)
        
    @delete_reminder.autocomplete("reminder_id")
    async def delete_reminder_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_item(interaction, "reminder", current)

    # Timer Commands
    @timer_group.command(name="start", description="Start a timer for a specific duration.")
    @app_commands.describe(duration="How long the timer should run (e.g., 30m, 1h15m, 10s).", name="An optional name for the timer.")
    async def start_timer(self, interaction: discord.Interaction, duration: str, name: Optional[str] = None):
        # The "message" for a timer is just its name, or a default string
        message = name or "Your timer is up."
        await self._create_item(interaction, "timer", duration, message)

    @timer_group.command(name="list", description="List your active timers.")
    async def list_timers(self, interaction: discord.Interaction):
        await self._list_items(interaction, "timer")

    @timer_group.command(name="cancel", description="Cancel an active timer using its ID.")
    @app_commands.describe(timer_id="The ID of the timer you want to cancel.")
    async def cancel_timer(self, interaction: discord.Interaction, timer_id: str):
        await self._delete_item(interaction, "timer", timer_id)
        
    @cancel_timer.autocomplete("timer_id")
    async def cancel_timer_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_item(interaction, "timer", current)

    # Shared Command Logic
    async def _create_item(self, interaction: discord.Interaction, item_type: str, when: str, message: str, repeat: Optional[app_commands.Choice[str]] = None):
        delta = self._parse_time(when)
        if delta is None or delta.total_seconds() <= 0:
            return await interaction.response.send_message(PERSONALITY["invalid_time"], ephemeral=True)

        now, due_time = datetime.now(timezone.utc), datetime.now(timezone.utc) + delta
        item_id = str(uuid.uuid4())[:8]
        
        new_item = {
            "id": item_id, "type": item_type, "user_id": interaction.user.id, "channel_id": interaction.channel_id,
            "guild_id": interaction.guild_id, "due_timestamp": int(due_time.timestamp()),
            "created_timestamp": int(now.timestamp()), "message": message,
            "repeat_interval": repeat.value if repeat and item_type == "reminder" else None
        }
        
        self.reminders.append(new_item)
        await self._save_json(self.reminders, self.reminders_file)
        
        if item_type == "reminder":
            response = PERSONALITY["reminder_set"].format(id=f'`{item_id}`')
        else: # Timer
            response = PERSONALITY["timer_set"].format(duration=when)
        
        await interaction.response.send_message(f"{response} I'll notify you at <t:{new_item['due_timestamp']}:F>.", ephemeral=True)

    async def _list_items(self, interaction: discord.Interaction, item_type: str):
        user_items = [r for r in self.reminders if r["user_id"] == interaction.user.id and r.get("type") == item_type]
        if not user_items:
            return await interaction.response.send_message(PERSONALITY["list_empty"].format(type=f"{item_type}s"), ephemeral=True)
            
        embed = discord.Embed(title=PERSONALITY["list_title"].format(type=item_type.capitalize()), color=discord.Color.blue())
        description = []
        for r in sorted(user_items, key=lambda x: x["due_timestamp"]):
            repeat_text = f" (Repeats {r['repeat_interval']})" if r.get("repeat_interval") else ""
            message_preview = r['message'][:40] + "..." if len(r['message']) > 40 else r['message']
            description.append(f"**ID:** `{r['id']}` - <t:{r['due_timestamp']}:R>{repeat_text}\n> {message_preview}")
        
        embed.description = "\n".join(description)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _delete_item(self, interaction: discord.Interaction, item_type: str, item_id: str):
        item_to_delete = next((r for r in self.reminders if r["id"] == item_id), None)
        
        if not item_to_delete or item_to_delete.get("type") != item_type:
            return await interaction.response.send_message(PERSONALITY["delete_not_found"].format(type=item_type), ephemeral=True)
        if item_to_delete["user_id"] != interaction.user.id:
            return await interaction.response.send_message(PERSONALITY["delete_not_yours"].format(type=item_type), ephemeral=True)

        self.reminders.remove(item_to_delete)
        await self._save_json(self.reminders, self.reminders_file)
        await interaction.response.send_message(PERSONALITY["deleted"].format(type=item_type), ephemeral=True)
        
    async def _autocomplete_item(self, interaction: discord.Interaction, item_type: str, current: str) -> List[app_commands.Choice[str]]:
        user_items = [r for r in self.reminders if r["user_id"] == interaction.user.id and r.get("type") == item_type]
        choices = []
        for r in user_items:
            preview = r['message'][:50] + "..." if len(r['message']) > 50 else r['message']
            choice_name = f"ID: {r['id']} | {preview}"
            if current.lower() in choice_name.lower():
                choices.append(app_commands.Choice(name=choice_name, value=r['id']))
        return choices[:25]
    
    @settings_group.command(name="delivery", description="Choose where Tika sends your reminders and timers.")
    @app_commands.describe(location="DM (private) or the original channel (public).")
    @app_commands.choices(location=[app_commands.Choice(name="Direct Message (DM)", value="dm"), app_commands.Choice(name="Original Channel", value="channel")])
    async def set_delivery(self, interaction: discord.Interaction, location: app_commands.Choice[str]):
        guild_id, user_id, remind_in_channel = str(interaction.guild_id), str(interaction.user.id), (location.value == "channel")
        self.user_settings.setdefault(guild_id, {}).setdefault(user_id, {})["remind_in_channel"] = remind_in_channel
        await self._save_json(self.user_settings, self.settings_file)
        response = PERSONALITY["delivery_channel"] if remind_in_channel else PERSONALITY["delivery_dm"]
        await interaction.response.send_message(response, ephemeral=True)
    
    @admin_group.command(name="list", description="List all active reminders for a specific user.")
    @app_commands.describe(user="The user whose reminders you want to see.")
    @BotAdmin.is_bot_admin()
    async def admin_list(self, interaction: discord.Interaction, user: discord.Member):
        user_reminders = [r for r in self.reminders if r["user_id"] == user.id and r.get("type") == "reminder"]
        if not user_reminders: return await interaction.response.send_message(PERSONALITY["admin_list_empty"], ephemeral=True)
        embed = discord.Embed(title=f"Active Reminders for {user.display_name}", color=discord.Color.orange())
        description = []
        for r in sorted(user_reminders, key=lambda x: x["due_timestamp"]):
            repeat_text = f" (Repeats {r['repeat_interval']})" if r.get('repeat_interval') else ""
            message_preview = r['message'][:40] + "..." if len(r['message']) > 40 else r['message']
            description.append(f"**ID:** `{r['id']}` - <t:{r['due_timestamp']}:R>{repeat_text}\n> {message_preview}")
        embed.description = "\n".join(description)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @admin_group.command(name="delete", description="Forcibly delete any user's reminder by its ID.")
    @app_commands.describe(reminder_id="The full ID of the reminder to delete.")
    # Is Admin? Check
    @BotAdmin.is_bot_admin()
    async def admin_delete(self, interaction: discord.Interaction, reminder_id: str):
        item_to_delete = next((r for r in self.reminders if r["id"] == reminder_id and r.get("type") == "reminder"), None)
        if not item_to_delete: return await interaction.response.send_message(PERSONALITY["delete_not_found"].format(type="reminder"), ephemeral=True)
        self.reminders.remove(item_to_delete)
        await self._save_json(self.reminders, self.reminders_file)
        await interaction.response.send_message(PERSONALITY["admin_deleted"].format(id=f"`{reminder_id}`"), ephemeral=True)
        
    # Helper Functions
    async def _send_notification(self, item: Dict):
        user = self.bot.get_user(item["user_id"])
        if not user: return

        guild_id, user_id = str(item["guild_id"]), str(user.id)
        channel = self.bot.get_channel(item["channel_id"])
        channel_name = channel.name if channel else 'Unknown Channel'
        
        is_timer = item.get("type") == "timer"
        
        embed = discord.Embed(
            description=item["message"], color=discord.Color.blue(),
            timestamp=datetime.fromtimestamp(item["created_timestamp"], tz=timezone.utc)
        )
        embed.set_footer(text=f"Set in: #{channel_name}")

        should_notify_in_channel = self.user_settings.get(guild_id, {}).get(user_id, {}).get("remind_in_channel", False)

        if should_notify_in_channel:
            if channel:
                embed.title = PERSONALITY["reminder_channel_title"].format(user=user.display_name) if not is_timer else PERSONALITY["timer_dm_title"]
                try: await channel.send(user.mention, embed=embed)
                except discord.Forbidden: pass
        else:
            embed.title = PERSONALITY["reminder_dm_title"] if not is_timer else PERSONALITY["timer_dm_title"]
            try: await user.send(embed=embed)
            except discord.Forbidden:
                if channel:
                    try: await channel.send(PERSONALITY["reminder_channel_ping"].format(user=user.mention), embed=embed)
                    except discord.Forbidden: pass
    
    def _create_next_occurrence(self, old_reminder: dict) -> Optional[dict]:
        interval = old_reminder.get("repeat_interval")
        if not interval: return None
        now, delta = datetime.now(timezone.utc), None
        if interval == "daily": delta = timedelta(days=1)
        elif interval == "weekly": delta = timedelta(weeks=1)
        elif interval == "monthly": delta = timedelta(days=30)
        else: return None
        new_due_time = now + delta
        new_reminder = old_reminder.copy()
        new_reminder["due_timestamp"] = int(new_due_time.timestamp())
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