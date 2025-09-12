# cogs/admin/bot_admin.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional

from config.personalities import PERSONALITY_RESPONSES

class BotAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["bot_admin"]
        self.data_manager = self.bot.data_manager

    @staticmethod
    def is_bot_admin():
        """A custom check to verify if a user has bot admin privileges."""
        async def predicate(interaction: discord.Interaction) -> bool:
            if interaction.user.guild_permissions.administrator:
                return True
            
            cog = interaction.client.get_cog('BotAdmin')
            if not cog: return False
            
            bot_admins_data = await cog.data_manager.get_data("bot_admins")
            guild_admins = bot_admins_data.get(str(interaction.guild_id), [])
            
            if interaction.user.id in guild_admins:
                return True
            
            await interaction.response.send_message(cog.personality["no_perm_check"], ephemeral=True)
            return False
        return app_commands.check(predicate)

    @app_commands.command(name="botadmin", description="Manage who can use Tika's admin commands.")
    @app_commands.default_permissions(administrator=True) # This hides the command from non-admins
    @app_commands.describe(
        action="The action to perform: add, remove, or list admins.",
        user="The user to add or remove (not required for list)."
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
        app_commands.Choice(name="List", value="list"),
    ])
    @is_bot_admin()
    async def manage_admins(self, interaction: discord.Interaction, action: str, user: Optional[discord.Member] = None):
        """A single command to add, remove, and list bot admins."""
        
        if action in ["add", "remove"] and not user:
            # Error messages should stay private
            await interaction.response.send_message("You must specify a user for that action. Obviously.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        bot_admins_data = await self.data_manager.get_data("bot_admins")
        guild_admins = bot_admins_data.setdefault(guild_id, [])

        # --- Add Logic ---
        if action == "add":
            if user.id in guild_admins:
                # Error messages should stay private
                return await interaction.response.send_message(self.personality["already_admin"], ephemeral=True)

            guild_admins.append(user.id)
            await self.data_manager.save_data("bot_admins", bot_admins_data)
            # This is now a PUBLIC message
            await interaction.response.send_message(self.personality["admin_added"].format(user=user.display_name))

        # --- Remove Logic ---
        elif action == "remove":
            if user.id not in guild_admins:
                # Error messages should stay private
                return await interaction.response.send_message(self.personality["not_admin"], ephemeral=True)

            guild_admins.remove(user.id)
            if not guild_admins:
                del bot_admins_data[guild_id]
            
            await self.data_manager.save_data("bot_admins", bot_admins_data)
            # This is now a PUBLIC message
            await interaction.response.send_message(self.personality["admin_removed"].format(user=user.display_name))

        # --- List Logic ---
        elif action == "list":
            if not guild_admins:
                # The admin list and related messages should stay private
                return await interaction.response.send_message(self.personality["no_admins"], ephemeral=True)

            embed = discord.Embed(title="Delegated Bot Admins", color=discord.Color.blue())
            admin_mentions = [f"<@{uid}>" for uid in guild_admins]
            embed.description = "\n".join(admin_mentions)
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(BotAdmin(bot))