# --- shared/utils/decorators.py ---

import discord
from discord import app_commands

def is_bot_admin():
    """
    A reusable slash command check to verify if a user has bot admin privileges.
    Checks for server administrators OR users on the manually-added admin list.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        # Rule 1: Server Admins are always bot admins.
        if interaction.user.guild_permissions.administrator:
            return True

        # Rule 2: Check the manually added list from the database.
        bot = interaction.client
        try:
            admin_plugin_data = await bot.data_manager.get_guild_data(interaction.guild_id, "admin")
            admin_list = admin_plugin_data.get("bot_admins", [])
            if interaction.user.id in admin_list:
                return True
        except Exception as e:
            bot.logger.error(f"Bot admin check failed in guild {interaction.guild_id}: {e}")
            return False

        # If neither rule is met, the check fails by returning False.
        # DO NOT send a response here, as the interaction may have timed out.
        return False
    return app_commands.check(predicate)