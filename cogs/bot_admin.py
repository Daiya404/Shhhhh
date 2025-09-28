import discord
from discord.ext import commands
from discord import app_commands
import logging
from core.personalities import PERSONALITY_RESPONSES

class BotAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["bot_admin"]
        self.data_manager = self.bot.data_manager
        self.config_cache = {}

    @commands.Cog.listener()
    async def on_ready(self):
        self.config_cache = await self.data_manager.get_data("server_config")

    def _get_admin_list(self, guild_id: int) -> list:
        """Helper to safely get the list of admin IDs for a guild."""
        return self.config_cache.setdefault(str(guild_id), {}).setdefault("bot_admins", [])

    async def is_user_bot_admin(self, user: discord.Member) -> bool:
        """Checks if a user is a server admin or a registered bot admin."""
        if user.guild_permissions.administrator:
            return True
        admin_list = self._get_admin_list(user.guild.id)
        return user.id in admin_list

    @app_commands.command(name="botadmin", description="Manage bot administrators.")
    @app_commands.default_permissions(administrator=True)
    async def botadmin(self, interaction: discord.Interaction, action: str, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only server administrators can manage bot admins.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        admin_list = self._get_admin_list(interaction.guild.id)
        
        if action.lower() == "add":
            if user.id in admin_list:
                await interaction.followup.send(self.personality["already_admin"])
            else:
                admin_list.append(user.id)
                await self.data_manager.save_data("server_config", self.config_cache)
                await interaction.followup.send(self.personality["admin_added"].format(user=user.mention))
        
        elif action.lower() == "remove":
            if user.id not in admin_list:
                await interaction.followup.send(self.personality["not_admin"])
            else:
                admin_list.remove(user.id)
                await self.data_manager.save_data("server_config", self.config_cache)
                await interaction.followup.send(self.personality["admin_removed"].format(user=user.mention))
        
        else:
            await interaction.followup.send("Invalid action. Use 'add' or 'remove'.")
    
    @app_commands.command(name="listadmins", description="Lists all current bot administrators.")
    @app_commands.default_permissions(administrator=True)
    async def listadmins(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        admin_list = self._get_admin_list(interaction.guild.id)
        if not admin_list:
            return await interaction.followup.send(self.personality["no_admins"])
        
        description = "\n".join([f"<@{admin_id}>" for admin_id in admin_list])
        embed = discord.Embed(title=self.personality["admin_list_title"], description=description, color=discord.Color.blue())
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BotAdmin(bot))