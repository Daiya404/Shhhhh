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

# --- Personality Responses for this Cog ---
PERSONALITY = {
    "reminder_set": "Fine, I'll remember that for you. It's not like I have anything better to do. Your reminder ID is `{id}`.",
    "reminder_dm_title": "Hey. You told me to remind you about this.",
    "reminder_channel_ping": "{user}, I tried to DM you, but you've got them blocked. You told me to remind you about this.",
    "reminder_channel_title": "A reminder for {user}!",
    "list_empty": "You haven't asked me to remember anything. Your memory must be better than I thought.",
    "admin_list_empty": "That user has no active reminders.",
    "list_title": "Things You Asked Me to Remember",
    "deleted": "Okay, I've forgotten about reminder `{id}`.",
    "admin_deleted": "Done. I have deleted reminder `{id}`.",
    "delete_not_found": "I can't find a reminder with that ID. Are you sure you typed it correctly?",
    "delete_not_yours": "That's not your reminder to delete. Mind your own business.",
    "invalid_time": "That doesn't look like a real time format. Use something like `1d`, `2h30m`, `tomorrow`, or `1 week`.",
    "delivery_dm": "Okay, I'll send your reminders via **Direct Message** from now on. I'll only ping you in the channel if I can't reach you.",
    "delivery_channel": "Got it. I'll send your reminders publicly in the **Original Channel** from now on."
}

class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.reminders_file = Path("data/reminders.json")
        self.settings_file = Path("data/user_settings.json")
        self.reminders: List[Dict] = self._load_json(self.reminders_file)
        # Data: {guild_id: {user_id: {"remind_in_channel": bool}}}
        self.user_settings: Dict[str, Dict] = self._load_json(self.settings_file)
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    def _load_json(self, file_path: Path) -> Dict: # Note: now returns Dict
        if not file_path.exists(): return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError):
            self.logger.error(f"Error loading {file_path}", exc_info=True)
            return {}

    async def _save_json(self, data, file_path: Path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except IOError:
            self.logger.error(f"Error saving {file_path}", exc_info=True)

    @tasks.loop(seconds=15)
    async def check_reminders(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc).timestamp()
        due_reminders = [r for r in self.reminders if r.get("due_timestamp", 0) <= now]
        if not due_reminders: return
        still_active = [r for r in self.reminders if r.get("due_timestamp", 0) > now]
        for reminder in due_reminders:
            await self._send_reminder(reminder)
            if reminder.get("repeat_interval"):
                if next_reminder := self._create_next_occurrence(reminder):
                    still_active.append(next_reminder)
        self.reminders = still_active
        await self._save_json(self.reminders, self.reminders_file)

    # --- Command Groups ---
    remind_group = app_commands.Group(name="remind", description="Set, view, or delete personal reminders.")
    settings_group = app_commands.Group(name="settings", parent=remind_group, description="Manage your personal reminder settings.")
    admin_group = app_commands.Group(name="remind-admin", description="Admin commands for managing reminders.")

    @remind_group.command(name="set", description="Set a reminder for the future.")
    @app_commands.describe(when="When to remind you (e.g., 1d 12h, 30m, tomorrow, 1 week).", message="What to remind you about.", repeat="Set a repeating interval for this reminder.")
    @app_commands.choices(repeat=[app_commands.Choice(name="Daily", value="daily"), app_commands.Choice(name="Weekly", value="weekly"), app_commands.Choice(name="Monthly", value="monthly")])
    async def set(self, interaction: discord.Interaction, when: str, message: str, repeat: Optional[app_commands.Choice[str]] = None):
        delta = self._parse_time(when)
        if delta is None: return await interaction.response.send_message(PERSONALITY["invalid_time"], ephemeral=True)
        now, due_time = datetime.now(timezone.utc), datetime.now(timezone.utc) + delta
        reminder_id = str(uuid.uuid4())[:8]
        new_reminder = {"reminder_id": reminder_id, "user_id": interaction.user.id, "channel_id": interaction.channel_id, "guild_id": interaction.guild_id, "due_timestamp": int(due_time.timestamp()), "created_timestamp": int(now.timestamp()), "message": message, "repeat_interval": repeat.value if repeat else None}
        self.reminders.append(new_reminder)
        await self._save_json(self.reminders, self.reminders_file)
        await interaction.response.send_message(f"{PERSONALITY['reminder_set'].format(id=f'`{reminder_id}`')} I'll remind you at <t:{new_reminder['due_timestamp']}:F>.", ephemeral=True)

    @remind_group.command(name="list", description="List your active reminders.")
    async def list(self, interaction: discord.Interaction):
        user_reminders = [r for r in self.reminders if r["user_id"] == interaction.user.id]
        if not user_reminders: return await interaction.response.send_message(PERSONALITY["list_empty"], ephemeral=True)
        embed = discord.Embed(title=PERSONALITY["list_title"], color=discord.Color.blue())
        description = []
        for r in sorted(user_reminders, key=lambda x: x["due_timestamp"]):
            repeat_text = f" (Repeats {r['repeat_interval']})" if r.get('repeat_interval') else ""
            message_preview = r['message'][:40] + "..." if len(r['message']) > 40 else r['message']
            description.append(f"**ID:** `{r['reminder_id']}` - <t:{r['due_timestamp']}:R>{repeat_text}\n> {message_preview}")
        embed.description = "\n".join(description)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @remind_group.command(name="delete", description="Delete an active reminder using its ID.")
    @app_commands.describe(reminder_id="The ID of the reminder you want to delete.")
    async def delete(self, interaction: discord.Interaction, reminder_id: str):
        reminder_to_delete = next((r for r in self.reminders if r["reminder_id"] == reminder_id), None)
        if not reminder_to_delete: return await interaction.response.send_message(PERSONALITY["delete_not_found"], ephemeral=True)
        if reminder_to_delete["user_id"] != interaction.user.id: return await interaction.response.send_message(PERSONALITY["delete_not_yours"], ephemeral=True)
        self.reminders.remove(reminder_to_delete)
        await self._save_json(self.reminders, self.reminders_file)
        await interaction.response.send_message(PERSONALITY["deleted"].format(id=f"`{reminder_id}`"), ephemeral=True)

    @delete.autocomplete("reminder_id")
    async def delete_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        user_reminders = [r for r in self.reminders if r["user_id"] == interaction.user.id]
        choices = []
        for r in user_reminders:
            preview = r['message'][:50] + "..." if len(r['message']) > 50 else r['message']
            choice_name = f"ID: {r['reminder_id']} | {preview}"
            if current.lower() in choice_name.lower():
                choices.append(app_commands.Choice(name=choice_name, value=r['reminder_id']))
        return choices[:25]
        
    @settings_group.command(name="delivery", description="Choose where Tika sends your reminders.")
    @app_commands.describe(location="DM (private) or the original channel (public).")
    @app_commands.choices(location=[
        app_commands.Choice(name="Direct Message (DM)", value="dm"),
        app_commands.Choice(name="Original Channel", value="channel"),
    ])
    async def set_delivery(self, interaction: discord.Interaction, location: app_commands.Choice[str]):
        """Sets the user's preferred reminder delivery location."""
        guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
        remind_in_channel = (location.value == "channel")

        self.user_settings.setdefault(guild_id, {}).setdefault(user_id, {})
        self.user_settings[guild_id][user_id]["remind_in_channel"] = remind_in_channel
        
        await self._save_json(self.user_settings, self.settings_file)
        
        response = PERSONALITY["delivery_channel"] if remind_in_channel else PERSONALITY["delivery_dm"]
        await interaction.response.send_message(response, ephemeral=True)
    
    @admin_group.command(name="list", description="List all active reminders for a specific user.")
    @app_commands.describe(user="The user whose reminders you want to see.")
    @BotAdmin.is_bot_admin()
    async def admin_list(self, interaction: discord.Interaction, user: discord.Member):
        user_reminders = [r for r in self.reminders if r["user_id"] == user.id]
        if not user_reminders: return await interaction.response.send_message(PERSONALITY["admin_list_empty"], ephemeral=True)
        embed = discord.Embed(title=f"Active Reminders for {user.display_name}", color=discord.Color.orange())
        description = []
        for r in sorted(user_reminders, key=lambda x: x["due_timestamp"]):
            repeat_text = f" (Repeats {r['repeat_interval']})" if r.get('repeat_interval') else ""
            message_preview = r['message'][:40] + "..." if len(r['message']) > 40 else r['message']
            description.append(f"**ID:** `{r['reminder_id']}` - <t:{r['due_timestamp']}:R>{repeat_text}\n> {message_preview}")
        embed.description = "\n".join(description)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="delete", description="Forcibly delete any user's reminder by its ID.")
    @app_commands.describe(reminder_id="The full ID of the reminder to delete.")
    @BotAdmin.is_bot_admin()
    async def admin_delete(self, interaction: discord.Interaction, reminder_id: str):
        reminder_to_delete = next((r for r in self.reminders if r["reminder_id"] == reminder_id), None)
        if not reminder_to_delete: return await interaction.response.send_message(PERSONALITY["delete_not_found"], ephemeral=True)
        self.reminders.remove(reminder_to_delete)
        await self._save_json(self.reminders, self.reminders_file)
        await interaction.response.send_message(PERSONALITY["admin_deleted"].format(id=f"`{reminder_id}`"), ephemeral=True)
        
    # --- Helper Functions ---
    async def _send_reminder(self, reminder: Dict):
        user = self.bot.get_user(reminder["user_id"])
        if not user: return

        guild_id, user_id = str(reminder["guild_id"]), str(user.id)
        channel = self.bot.get_channel(reminder["channel_id"])
        channel_name = channel.name if channel else 'Unknown Channel'
        
        embed = discord.Embed(
            description=reminder["message"], color=discord.Color.blue(),
            timestamp=datetime.fromtimestamp(reminder["created_timestamp"], tz=timezone.utc)
        )
        embed.set_footer(text=f"Set in: #{channel_name}")

        # --- NEW DELIVERY LOGIC ---
        should_remind_in_channel = self.user_settings.get(guild_id, {}).get(user_id, {}).get("remind_in_channel", False)

        if should_remind_in_channel:
            # User explicitly chose to be reminded in the channel
            if channel:
                embed.title = PERSONALITY["reminder_channel_title"].format(user=user.display_name)
                try: await channel.send(user.mention, embed=embed)
                except discord.Forbidden: pass # Can't send in channel
        else:
            # Default behavior: Try DM first, then fall back to channel
            embed.title = PERSONALITY["reminder_dm_title"]
            try:
                await user.send(embed=embed)
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