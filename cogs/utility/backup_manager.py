# cogs/utility/backup_manager.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
from typing import Optional

from cogs.admin.bot_admin import is_bot_admin

class BackupManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.backup_service = getattr(bot, 'backup_service', None)

    @app_commands.command(name="backup", description="[Admin] Create a backup of bot data.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        action="What to do with backups",
        list_count="Number of recent backups to show (for list action)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Create Backup Now", value="create"),
        app_commands.Choice(name="List Recent Backups", value="list"),
        app_commands.Choice(name="Clean Old Backups", value="clean")
    ])
    async def backup(self, interaction: discord.Interaction, action: str, list_count: Optional[int] = 5):
        if not self.backup_service or not self.backup_service.is_ready():
            return await interaction.response.send_message(
                "Backup service isn't configured. Someone didn't set it up properly.", 
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        if action == "create":
            await interaction.followup.send("Fine, I'll create a backup. Give me a moment...")
            
            success = await self.backup_service.perform_backup()
            if success:
                await interaction.edit_original_response(
                    content="Backup complete. Your data is safe, I suppose."
                )
            else:
                await interaction.edit_original_response(
                    content="Something went wrong with the backup. Check the logs."
                )

        elif action == "list":
            backups = await self.backup_service.list_backups()
            if not backups:
                return await interaction.followup.send("No backups found. Maybe create one first?")
            
            backup_list = []
            for i, backup in enumerate(backups[:list_count or 5]):
                if hasattr(backup, 'get'):  # GitHub format
                    name = backup.get('name', 'Unknown')
                    backup_list.append(f"{i+1}. `{name}`")
                elif isinstance(backup, dict):  # Discord format
                    name = backup.get('filename', 'Unknown')
                    size_mb = backup.get('size', 0) / (1024*1024)
                    backup_list.append(f"{i+1}. `{name}` ({size_mb:.1f}MB)")
                    
            embed = discord.Embed(
                title="Recent Backups",
                description="\n".join(backup_list) or "None found",
                color=0x5865F2
            )
            await interaction.followup.send(embed=embed)

        elif action == "clean":
            if hasattr(self.backup_service, 'delete_old_backups'):
                deleted = await self.backup_service.delete_old_backups(keep_count=5)
                await interaction.followup.send(
                    f"Cleaned up {deleted} old backup(s). Kept the 5 most recent ones."
                )
            else:
                await interaction.followup.send("This backup service doesn't support cleaning old backups.")

async def setup(bot):
    await bot.add_cog(BackupManager(bot))