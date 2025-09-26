# cogs/admin.py
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from core.personality import PERSONALITY

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.p = PERSONALITY

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Global check for all commands in this cog to ensure user is an admin."""
        is_admin = await self.bot.admin_manager.is_bot_admin(interaction.user)
        if not is_admin:
            await interaction.response.send_message(self.p["general"]["permission_denied"], ephemeral=True)
        return is_admin

    # Group for /botadmin commands
    botadmin_group = app_commands.Group(name="botadmin", description="Manage who can use Tika's admin commands.")

    @botadmin_group.command(name="add", description="Add a delegated bot admin.")
    async def add_admin(self, interaction: discord.Interaction, user: discord.Member):
        guild_id = interaction.guild.id
        admins = self.bot.admin_manager.get_guild_admins(guild_id)
        if user.id in admins:
            return await interaction.response.send_message(self.p["admin"]["already_admin"], ephemeral=True)
        
        await self.bot.admin_manager.add_admin(guild_id, user.id)
        await interaction.response.send_message(self.p["admin"]["admin_added"].format(user=user.display_name))

    @botadmin_group.command(name="remove", description="Remove a delegated bot admin.")
    async def remove_admin(self, interaction: discord.Interaction, user: discord.Member):
        guild_id = interaction.guild.id
        admins = self.bot.admin_manager.get_guild_admins(guild_id)
        if user.id not in admins:
            return await interaction.response.send_message(self.p["admin"]["not_admin"], ephemeral=True)

        await self.bot.admin_manager.remove_admin(guild_id, user.id)
        await interaction.response.send_message(self.p["admin"]["admin_removed"].format(user=user.display_name))

    @botadmin_group.command(name="list", description="List all delegated bot admins.")
    async def list_admins(self, interaction: discord.Interaction):
        admins = self.bot.admin_manager.get_guild_admins(interaction.guild.id)
        if not admins:
            return await interaction.response.send_message(self.p["admin"]["no_admins"], ephemeral=True)
        
        embed = discord.Embed(title=self.p["admin"]["list_admins_title"], color=discord.Color.blue())
        embed.description = "\n".join([f"<@{uid}>" for uid in admins])
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Group for /feature commands
    feature_group = app_commands.Group(name="feature", description="Enable or disable bot features for this server.")

    @feature_group.command(name="toggle", description="Enable or disable a feature.")
    @app_commands.describe(feature="The feature to toggle.", status="The new status for the feature.")
    @app_commands.choices(status=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
    ])
    async def toggle_feature(self, interaction: discord.Interaction, feature: str, status: str):
        guild_id = interaction.guild.id
        fm = self.bot.feature_manager
        
        if feature not in fm.available_features:
            return await interaction.response.send_message(self.p["feature"]["feature_not_found"].format(feature=feature), ephemeral=True)
            
        is_enabled = await fm.is_enabled(guild_id, feature)

        if status == "enable":
            if is_enabled:
                return await interaction.response.send_message(self.p["feature"]["already_enabled"], ephemeral=True)
            await fm.enable_feature(guild_id, feature)
            await interaction.response.send_message(self.p["feature"]["feature_enabled"].format(feature=feature))
        else: # disable
            if not is_enabled:
                return await interaction.response.send_message(self.p["feature"]["already_disabled"], ephemeral=True)
            await fm.disable_feature(guild_id, feature)
            await interaction.response.send_message(self.p["feature"]["feature_disabled"].format(feature=feature))

    @feature_group.command(name="list", description="List the status of all available features.")
    async def list_features(self, interaction: discord.Interaction):
        fm = self.bot.feature_manager
        embed = discord.Embed(title=self.p["feature"]["list_features_title"], color=discord.Color.purple())
        
        description = []
        for feature in sorted(fm.available_features):
            is_enabled = await fm.is_enabled(interaction.guild.id, feature)
            status_icon = "✅" if is_enabled else "❌"
            description.append(f"{status_icon} `{feature}`")
            
        embed.description = "\n".join(description)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))