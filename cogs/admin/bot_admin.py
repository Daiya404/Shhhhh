# cogs/admin/bot_admin.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Dict, List

from config.personalities import PERSONALITY_RESPONSES

class BotAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["bot_admin"]
        self.data_manager = self.bot.data_manager
        # No more self.bot_admins, we will fetch it when needed.

    # The static check method needs to be updated to find the cog
    @staticmethod
    def is_bot_admin():
        async def predicate(interaction: discord.Interaction) -> bool:
            if interaction.user.guild_permissions.administrator:
                return True
            
            # Correctly access the cog and its data manager
            cog = interaction.client.get_cog('BotAdmin')
            if not cog: return False # Cog might not be loaded
            
            bot_admins_data = await cog.data_manager.get_data("bot_admins")
            guild_admins = bot_admins_data.get(str(interaction.guild_id), [])
            
            if interaction.user.id in guild_admins:
                return True
            
            await interaction.response.send_message(cog.personality["no_perm_check"], ephemeral=True)
            return False
        return app_commands.check(predicate)

    admin_group = app_commands.Group(
        name="botadmin",
        description="Manage who can use Tika's admin commands.",
        default_permissions=discord.Permissions(administrator=True)
    )

    @admin_group.command(name="add", description="Allow a user to use admin commands.")
    async def add(self, interaction: discord.Interaction, user: discord.Member):
        bot_admins_data = await self.data_manager.get_data("bot_admins")
        guild_id = str(interaction.guild.id)
        
        guild_admins = bot_admins_data.setdefault(guild_id, [])

        if user.id in guild_admins:
            return await interaction.response.send_message(self.personality["already_admin"], ephemeral=True)

        guild_admins.append(user.id)
        await self.data_manager.save_data("bot_admins", bot_admins_data)
        
        await interaction.response.send_message(self.personality["admin_added"].format(user=user.display_name), ephemeral=True)

    @admin_group.command(name="remove", description="Revoke a user's admin command permissions.")
    async def remove(self, interaction: discord.Interaction, user: discord.Member):
        bot_admins_data = await self.data_manager.get_data("bot_admins")
        guild_id = str(interaction.guild.id)
        
        guild_admins = bot_admins_data.get(guild_id, [])

        if user.id not in guild_admins:
            return await interaction.response.send_message(self.personality["not_admin"], ephemeral=True)

        guild_admins.remove(user.id)
        if not guild_admins:
            del bot_admins_data[guild_id] # Clean up empty list

        await self.data_manager.save_data("bot_admins", bot_admins_data)
        await interaction.response.send_message(self.personality["admin_removed"].format(user=user.display_name), ephemeral=True)

    # ... (refactor the 'list' command in the same way) ...
    @admin_group.command(name="list", description="List all non-admin users with bot admin permissions.")
    async def list(self, interaction: discord.Interaction):
        bot_admins_data = await self.data_manager.get_data("bot_admins")
        guild_id = str(interaction.guild.id)
        
        admin_ids = bot_admins_data.get(guild_id, [])
        
        if not admin_ids:
            return await interaction.response.send_message(self.personality["no_admins"], ephemeral=True)

        embed = discord.Embed(title="Delegated Bot Admins", color=discord.Color.blue())
        admin_mentions = [f"<@{uid}>" for uid in admin_ids]
        embed.description = "\n".join(admin_mentions)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(BotAdmin(bot))