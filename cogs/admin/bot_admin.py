# cogs/admin/bot_admin.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional
import asyncio # Add asyncio import

from config.personalities import PERSONALITY_RESPONSES

# --- The decorator is a standalone function ---
def is_bot_admin():
    """A custom decorator that checks if a user is a bot admin."""
    
    async def predicate(interaction: discord.Interaction) -> bool:
        """The actual check logic."""
        # Rule 1: Server Admins are always bot admins.
        if interaction.user.guild_permissions.administrator:
            return True
        
        cog = interaction.client.get_cog('BotAdmin')
        if not cog:
            try:
                # Check if response is already done before sending
                if not interaction.response.is_done():
                    await interaction.response.send_message("The BotAdmin module isn't loaded.", ephemeral=True)
            except discord.InteractionResponded:
                pass # Already responded to, can't send another message
            return False
            
        # Rule 2: Check the manually added list from the cog's data.
        bot_admins_data = await cog.data_manager.get_data("bot_admins")
        guild_admins = bot_admins_data.get(str(interaction.guild_id), [])
        
        if interaction.user.id in guild_admins:
            return True
        
        # If neither rule is met, deny permission.
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(cog.personality["no_perm_check"], ephemeral=True)
        except discord.InteractionResponded:
            pass
        return False
    
    return app_commands.check(predicate)


class BotAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["bot_admin"]
        self.data_manager = self.bot.data_manager

    # --- SIMPLIFIED AND CORRECTED PREFIX COMMAND CHECK ---
    async def check_prefix_command(self, ctx: commands.Context) -> bool:
        """The core logic for checking if a user is a bot admin for prefix commands."""
        
        # Rule 1: Server Admins are always bot admins.
        if ctx.author.guild_permissions.administrator:
            return True
        
        # Rule 2: Check the manually added list.
        bot_admins_data = await self.data_manager.get_data("bot_admins")
        guild_admins = bot_admins_data.get(str(ctx.guild.id), [])
        
        return ctx.author.id in guild_admins

    @app_commands.command(name="botadmin", description="Manage who can use Tika's admin commands.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(action="Add, remove, or list admins.", user="The user to manage (not required for list).")
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
        app_commands.Choice(name="List", value="list"),
    ])
    async def manage_admins(self, interaction: discord.Interaction, action: str, user: Optional[discord.Member] = None):
        # This command is correct.
        if action in ["add", "remove"] and not user:
            return await interaction.response.send_message("You must specify a user for that action.", ephemeral=True)

        guild_id = str(interaction.guild.id)
        bot_admins_data = await self.data_manager.get_data("bot_admins")
        guild_admins = bot_admins_data.setdefault(guild_id, [])

        if action == "add":
            if user.id in guild_admins:
                return await interaction.response.send_message(self.personality["already_admin"], ephemeral=True)
            guild_admins.append(user.id)
            await self.data_manager.save_data("bot_admins", bot_admins_data)
            await interaction.response.send_message(self.personality["admin_added"].format(user=user.display_name))
        
        elif action == "remove":
            if user.id not in guild_admins:
                return await interaction.response.send_message(self.personality["not_admin"], ephemeral=True)
            guild_admins.remove(user.id)
            if not guild_admins: del bot_admins_data[guild_id]
            await self.data_manager.save_data("bot_admins", bot_admins_data)
            await interaction.response.send_message(self.personality["admin_removed"].format(user=user.display_name))

        elif action == "list":
            if not guild_admins:
                return await interaction.response.send_message(self.personality["no_admins"], ephemeral=True)
            embed = discord.Embed(title="Delegated Bot Admins", color=discord.Color.blue(), description="\n".join([f"<@{uid}>" for uid in guild_admins]))
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(BotAdmin(bot))