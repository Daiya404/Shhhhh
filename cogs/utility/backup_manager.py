# cogs/utility/backup_manager.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional

from cogs.admin.bot_admin import is_bot_admin

class BackupManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # FIX: Grab the existing service instance directly from the bot.
        self.backup_service = getattr(bot, 'backup_service', None)
        
        # FIX: If the service exists, inject the bot's event loop into it.
        # This is what enables the non-blocking functionality.
        if self.backup_service:
            self.backup_service.loop = bot.loop

    @app_commands.command(name="backup", description="[Admin] Manage bot data backups.")
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
    async def backup(self, interaction: discord.Interaction, action: str, list_count: Optional[app_commands.Range[int, 1, 25]] = 5):
        if not self.backup_service or not self.backup_service.is_ready():
            return await interaction.response.send_message(
                "Backup service isn't configured. Someone didn't set it up properly.", 
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        if action == "create":
            await interaction.followup.send("Fine, I'll create a backup. Preparing archive...")
            success, message = await self.backup_service.perform_backup()
            await interaction.edit_original_response(content=message)

        elif action == "list":
            backups = await self.backup_service.list_backups()
            if not backups:
                return await interaction.followup.send("No backups found. Maybe create one first?")
            
            backup_list = [f"{i+1}. `{backup.get('name', 'Unknown')}`" for i, backup in enumerate(backups[:list_count])]
                    
            embed = discord.Embed(
                title=f"Showing {len(backup_list)} Most Recent Backups",
                description="\n".join(backup_list),
                color=0x5865F2
            )
            await interaction.followup.send(embed=embed)

        elif action == "clean":
            await interaction.followup.send("Checking for old backups to clean...")
            deleted_count = await self.backup_service.delete_old_backups(keep_count=5)
            message = f"Cleaned up {deleted_count} old backup(s)." if deleted_count > 0 else "No old backups needed cleaning."
            await interaction.edit_original_response(content=message)

async def setup(bot):
    await bot.add_cog(BackupManager(bot))