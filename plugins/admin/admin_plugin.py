import discord
from discord import app_commands
from datetime import datetime

from plugins.base_plugin import BasePlugin
from shared.utils.decorators import is_bot_admin

# Responses for this plugin's commands
PERSONALITY = {
    "admin_added": "Fine, I'll acknowledge `{user}`'s commands now. You're taking responsibility for them.",
    "admin_removed": "Noted. `{user}` is no longer a bot admin.",
    "already_admin": "That person is already on the list. Pay attention.",
    "not_admin": "I wasn't listening to that person anyway.",
    "no_admins": "No extra bot admins have been added. It's just the server administrators.",
}

class AdminPlugin(BasePlugin):
    # --- BasePlugin Implementation ---
    @property
    def name(self) -> str:
        return "admin"

    # --- Command Group Definitions ---
    # This creates the `/botadmin` "folder" for our commands.
    # It is restricted to server administrators by default.
    admin_group = app_commands.Group(
        name="botadmin",
        description="Manage who can use Tika's admin commands.",
        default_permissions=discord.Permissions(administrator=True)
    )

    # --- Bot Admin Management Commands ---
    @admin_group.command(name="add", description="Allow a user to use admin commands.")
    @app_commands.describe(user="The user to grant permissions to.")
    async def add_admin(self, interaction: discord.Interaction, user: discord.Member):
        guild_data = await self.db.get_guild_data(interaction.guild_id, self.name)
        admins = guild_data.setdefault("bot_admins", [])

        if user.id in admins:
            return await interaction.response.send_message(PERSONALITY["already_admin"], ephemeral=True)

        admins.append(user.id)
        await self.db.save_guild_data(interaction.guild_id, self.name, guild_data)
        await interaction.response.send_message(PERSONALITY["admin_added"].format(user=user.display_name), ephemeral=True)

    @admin_group.command(name="remove", description="Revoke a user's admin command permissions.")
    @app_commands.describe(user="The user to revoke permissions from.")
    async def remove_admin(self, interaction: discord.Interaction, user: discord.Member):
        guild_data = await self.db.get_guild_data(interaction.guild_id, self.name)
        admins = guild_data.get("bot_admins", [])

        if user.id not in admins:
            return await interaction.response.send_message(PERSONALITY["not_admin"], ephemeral=True)

        admins.remove(user.id)
        await self.db.save_guild_data(interaction.guild_id, self.name, guild_data)
        await interaction.response.send_message(PERSONALITY["admin_removed"].format(user=user.display_name), ephemeral=True)

    @admin_group.command(name="list", description="List all non-admin users with bot admin permissions.")
    async def list_admins(self, interaction: discord.Interaction):
        guild_data = await self.db.get_guild_data(interaction.guild_id, self.name)
        admins = guild_data.get("bot_admins", [])

        if not admins:
            return await interaction.response.send_message(PERSONALITY["no_admins"], ephemeral=True)

        embed = discord.Embed(title="Delegated Bot Admins", color=discord.Color.blue())
        admin_mentions = [f"<@{uid}>" for uid in admins]
        embed.description = "\n".join(admin_mentions)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Server Stats Command ---
    @app_commands.command(name="server-stats", description="Display detailed statistics about the server.")
    @is_bot_admin() # Using our new reusable decorator!
    async def server_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        embed = discord.Embed(
            title=f"📊 Server Stats for {guild.name}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        # General Info
        owner = guild.owner.mention if guild.owner else "Unknown"
        created_at = f"<t:{int(guild.created_at.timestamp())}:F>"
        embed.add_field(
            name="📋 General Info",
            value=f"**Owner:** {owner}\n**Created:** {created_at}",
            inline=False
        )

        # Member Counts
        total_members = guild.member_count or 0
        humans = sum(1 for member in guild.members if not member.bot)
        bots = total_members - humans
        embed.add_field(
            name="👥 Member Counts",
            value=f"**Total:** {total_members}\n**Humans:** {humans}\n**Bots:** {bots}",
            inline=True
        )

        # Asset Counts
        embed.add_field(
            name="📦 Asset Counts",
            value=f"**Text Channels:** {len(guild.text_channels)}\n"
                  f"**Voice Channels:** {len(guild.voice_channels)}\n"
                  f"**Roles:** {len(guild.roles)}",
            inline=True
        )

        await interaction.followup.send(embed=embed)