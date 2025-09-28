import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional

# This utility check is fine as is.
def is_bot_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        bot_admin_cog = interaction.client.get_cog("BotAdmin")
        if not bot_admin_cog:
            return interaction.user.guild_permissions.administrator
        return await bot_admin_cog.is_user_bot_admin(interaction.user)
    return app_commands.check(predicate)

class Backup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # CORRECTED: Access the 'backup' section directly from bot.personalities
        self.personality = self.bot.personalities["backup"]
        self.backup_service = self.bot.backup_service

    @app_commands.command(name="backup", description="[Admin] Manage bot data backups.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        action="Choose an action to perform.",
        list_count="Number of recent backups to show (for 'list' action)."
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Create Backup Now", value="create"),
        app_commands.Choice(name="List Recent Backups", value="list"),
        app_commands.Choice(name="Clean Old Backups", value="clean")
    ])
    async def backup(self, interaction: discord.Interaction, action: str, list_count: Optional[app_commands.Range[int, 1, 20]] = 5):
        if not self.backup_service or not self.backup_service.is_ready():
            await interaction.response.send_message(self.personality["service_not_configured"], ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if action == "create":
            await interaction.followup.send(self.personality["create_start"])
            success, message = await self.backup_service.perform_backup()
            await interaction.edit_original_response(content=message)

        elif action == "list":
            # ... (rest of the file is unchanged)
            backups = await self.backup_service.list_backups()
            if not backups:
                await interaction.followup.send(self.personality["no_backups_found"])
                return
            
            backup_list = [f"**{i+1}.** `{b['name']}`" for i, b in enumerate(backups[:list_count])]
            
            embed = discord.Embed(
                title=self.personality["list_title"],
                description="\n".join(backup_list),
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed)

        elif action == "clean":
            await interaction.followup.send(self.personality["clean_start"])
            deleted_count = await self.backup_service.delete_old_backups(keep_count=5)
            
            if deleted_count > 0:
                message = self.personality["clean_complete"].format(count=deleted_count)
            else:
                message = self.personality["clean_unnecessary"]
            
            await interaction.edit_original_response(content=message)

async def setup(bot):
    await bot.add_cog(Backup(bot))