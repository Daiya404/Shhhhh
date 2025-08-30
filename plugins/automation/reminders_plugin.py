# --- plugins/automation/reminders_plugin.py ---

import discord
from discord.ext import tasks
from discord import app_commands
import time
import uuid
from datetime import datetime, timedelta, timezone

from plugins.base_plugin import BasePlugin

class RemindersPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "reminders"

    def __init__(self, bot):
        super().__init__(bot)
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    @tasks.loop(seconds=15)
    async def check_reminders(self):
        await self.bot.wait_until_ready()
        now = time.time()
        # In a real scenario, you'd iterate over all guilds.
        # For this example, we simplify by assuming a single global list.
        # A better approach would be to get a list of all guilds with reminders.
        all_reminders = await self.db.get_guild_data(0, "global_reminders") # Using a placeholder ID for global data
        if not all_reminders.get("items"): return

        due = [r for r in all_reminders["items"] if r.get("due_timestamp", 0) <= now]
        if not due: return

        still_active = [r for r in all_reminders["items"] if r.get("due_timestamp", 0) > now]
        all_reminders["items"] = still_active
        await self.db.save_guild_data(0, "global_reminders", all_reminders)

        for item in due:
            user = self.bot.get_user(item["user_id"])
            if user:
                embed = discord.Embed(
                    title="⏰ Reminder!",
                    description=item["message"],
                    color=discord.Color.blue(),
                    timestamp=datetime.fromtimestamp(item["created_timestamp"], tz=timezone.utc)
                )
                try:
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass # Can't DM user

    # Command implementation for /remind and /timer would go here
    # This is a simplified example to show the structure. The full command
    # logic from the old file can be ported over.
    @app_commands.command(name="remindme", description="Set a personal reminder.")
    @app_commands.describe(when="e.g., '1d 2h', '30m', '1 week'", message="What to remind you about.")
    async def remindme(self, interaction: discord.Interaction, when: str, message: str):
        # A very basic time parser
        # In a real app, use a proper parsing library
        seconds = 0
        if "d" in when: seconds += int(when.split("d")[0]) * 86400
        if "h" in when: seconds += int(when.split("h")[0]) * 3600
        if "m" in when: seconds += int(when.split("m")[0]) * 60
        if "s" in when: seconds += int(when.split("s")[0])
        
        if seconds == 0:
            return await interaction.response.send_message("Invalid time format.", ephemeral=True)

        due_time = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        
        all_reminders = await self.db.get_guild_data(0, "global_reminders")
        items = all_reminders.setdefault("items", [])
        
        new_item = {
            "id": str(uuid.uuid4())[:8],
            "user_id": interaction.user.id,
            "due_timestamp": int(due_time.timestamp()),
            "created_timestamp": int(time.time()),
            "message": message,
        }
        items.append(new_item)
        await self.db.save_guild_data(0, "global_reminders", all_reminders)
        
        await interaction.response.send_message(f"Okay, I'll remind you <t:{new_item['due_timestamp']}:R>.", ephemeral=True)