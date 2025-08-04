import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
from typing import Dict, List

# personality for this cog's responses
PERSONALITY = {
    "admin_added": "Fine, I'll acknowledge `{user}`'s commands now. You're taking responsibility for them. 😒",
    "admin_removed": "Noted. `{user}` is no longer a bot admin.",
    "already_admin": "That person is already on the list. Pay attention.",
    "not_admin": "I wasn't listening to that person anyway. Can't remove someone who isn't there.",
    "no_admins": "No extra bot admins have been added. It's just the server administrators.",
    "no_perm_check": "You don't have the required permissions for that command.",
    "no_perm_group": "That command is for server administrators only. Don't waste my time."
}

class BotAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.admins_file = Path("data/bot_admins.json")
        self.bot_admins: Dict[str, List[int]] = self._load_json()

    def _load_json(self) -> dict:
        if not self.admins_file.exists(): return {}
        try:
            with open(self.admins_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Error loading {self.admins_file}: {e}", exc_info=True)
            return {}

    async def _save_json(self):
        try:
            with open(self.admins_file, 'w', encoding='utf-8') as f:
                json.dump(self.bot_admins, f, indent=2)
        except IOError as e:
            self.logger.error(f"Error saving {self.admins_file}: {e}", exc_info=True)

    # Is Admin? check
    def is_bot_admin():
        """A custom check to verify if a user has bot admin privileges."""
        async def predicate(interaction: discord.Interaction) -> bool:
            # Rule 1: Server Admins are always bot admins.
            if interaction.user.guild_permissions.administrator:
                return True
            
            # Rule 2: Check the manually added list.
            cog = interaction.client.get_cog('BotAdmin')
            if not cog: return False
            
            guild_id = str(interaction.guild_id)
            if guild_id in cog.bot_admins and interaction.user.id in cog.bot_admins[guild_id]:
                return True
            
            # If neither rule is met, deny permission.
            await interaction.response.send_message(PERSONALITY["no_perm_check"], ephemeral=True)
            return False
        return app_commands.check(predicate)

    # Command Group Definition
    # This single line creates the `/botadmin` "folder" for our commands.
    # It is restricted to server administrators by default.
    admin_group = app_commands.Group(
        name="botadmin",
        description="Manage who can use Tika's admin commands.",
        default_permissions=discord.Permissions(administrator=True))

    @admin_group.command(name="add", description="Allow a user to use admin commands.")
    @app_commands.describe(user="The user to grant permissions to.")
    async def add(self, interaction: discord.Interaction, user: discord.Member):
        guild_id = str(interaction.guild.id)
        if guild_id not in self.bot_admins:
            self.bot_admins[guild_id] = []
        
        if user.id in self.bot_admins[guild_id]:
            await interaction.response.send_message(PERSONALITY["already_admin"], ephemeral=True)
            return

        self.bot_admins[guild_id].append(user.id)
        await self._save_json()
        await interaction.response.send_message(PERSONALITY["admin_added"].format(user=user.display_name), ephemeral=True)

    @admin_group.command(name="remove", description="Revoke a user's admin command permissions.")
    @app_commands.describe(user="The user to revoke permissions from.")
    async def remove(self, interaction: discord.Interaction, user: discord.Member):
        guild_id = str(interaction.guild.id)
        if guild_id not in self.bot_admins or user.id not in self.bot_admins[guild_id]:
            await interaction.response.send_message(PERSONALITY["not_admin"], ephemeral=True)
            return

        self.bot_admins[guild_id].remove(user.id)
        if not self.bot_admins[guild_id]:
            del self.bot_admins[guild_id]
        await self._save_json()
        await interaction.response.send_message(PERSONALITY["admin_removed"].format(user=user.display_name), ephemeral=True)

    @admin_group.command(name="list", description="List all non-admin users with bot admin permissions.")
    async def list(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        if guild_id not in self.bot_admins or not self.bot_admins[guild_id]:
            await interaction.response.send_message(PERSONALITY["no_admins"], ephemeral=True)
            return

        embed = discord.Embed(title="Delegated Bot Admins", color=discord.Color.blue())
        admin_mentions = [f"<@{uid}>" for uid in self.bot_admins[guild_id]]
        embed.description = "\n".join(admin_mentions)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(BotAdmin(bot))