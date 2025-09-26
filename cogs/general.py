# cogs/general.py
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import logging
import random

logger = logging.getLogger(__name__)

class General(commands.Cog):
    """General purpose commands for all users."""
    
    def __init__(self, bot):
        self.bot = bot
        self.personality = bot.personality
    
    async def cog_check(self, ctx):
        """Check if the general feature is enabled for commands."""
        if hasattr(ctx, 'interaction') and ctx.interaction:
            # This is a slash command
            return await self.bot.feature_manager.is_enabled(ctx.guild.id, "general")
        return True  # For non-slash commands or if no guild context
    
    @app_commands.command(name="hello", description="A friendly greeting from the bot")
    @app_commands.describe(user="Optionally mention a specific user")
    async def hello(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Send a greeting message."""
        try:
            # Check if feature is enabled
            if not await self.bot.feature_manager.is_enabled(interaction.guild.id, "general"):
                return await interaction.response.send_message(
                    self.personality.get("general", "feature_disabled"),
                    ephemeral=True
                )
            
            # Determine if this user is a "friend" (could be expanded with friendship system)
            is_friend = await self.bot.admin_manager.is_bot_admin(interaction.user)
            target_user = user or interaction.user
            
            if is_friend:
                message = self.personality.get(
                    "hello", 
                    "response_friend", 
                    user=target_user.display_name
                )
            else:
                message = self.personality.get("hello", "response")
            
            # Add some variation
            if user and user != interaction.user:
                message = f"{target_user.mention}, {message.lower()}"
            
            await interaction.response.send_message(message)
            
        except Exception as e:
            logger.error(f"Error in hello command: {e}")
            await interaction.response.send_message(
                self.personality.get("general", "error"),
                ephemeral=True
            )
    
    @app_commands.command(name="ping", description="Check bot response time")
    async def ping(self, interaction: discord.Interaction):
        """Check the bot's latency."""
        try:
            if not await self.bot.feature_manager.is_enabled(interaction.guild.id, "general"):
                return await interaction.response.send_message(
                    self.personality.get("general", "feature_disabled"),
                    ephemeral=True
                )
            
            latency = round(self.bot.latency * 1000)
            
            # Color code based on latency
            if latency < 100:
                color = discord.Color.green()
                status = "Excellent"
            elif latency < 200:
                color = discord.Color.yellow()
                status = "Good"
            else:
                color = discord.Color.red()
                status = "Poor"
            
            embed = discord.Embed(
                title="🏓 Pong!",
                description=f"**Latency:** {latency}ms ({status})",
                color=color,
                timestamp=discord.utils.utcnow()
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in ping command: {e}")
            await interaction.response.send_message(
                "Failed to get ping information.",
                ephemeral=True
            )
    
    @app_commands.command(name="serverinfo", description="Show information about the current server")
    async def server_info(self, interaction: discord.Interaction):
        """Display server information."""
        try:
            if not await self.bot.feature_manager.is_enabled(interaction.guild.id, "general"):
                return await interaction.response.send_message(
                    self.personality.get("general", "feature_disabled"),
                    ephemeral=True
                )
            
            guild = interaction.guild
            
            # Count members by status
            online_members = sum(1 for m in guild.members if m.status == discord.Status.online)
            total_members = guild.member_count
            
            embed = discord.Embed(
                title=guild.name,
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            # Basic server info
            embed.add_field(
                name="📊 Server Stats",
                value=(
                    f"**Owner:** {guild.owner.mention if guild.owner else 'Unknown'}\n"
                    f"**Created:** <t:{int(guild.created_at.timestamp())}:R>\n"
                    f"**Members:** {total_members} ({online_members} online)\n"
                    f"**Channels:** {len(guild.channels)}\n"
                    f"**Roles:** {len(guild.roles)}"
                ),
                inline=True
            )
            
            # Features
            features = []
            if guild.premium_tier > 0:
                features.append(f"Boost Level {guild.premium_tier}")
            if guild.verification_level != discord.VerificationLevel.none:
                features.append(f"Verification: {guild.verification_level.name}")
            
            if features:
                embed.add_field(
                    name="✨ Features",
                    value="\n".join(features),
                    inline=True
                )
            
            embed.add_field(
                name="🆔 Server ID",
                value=f"`{guild.id}`",
                inline=False
            )
            
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            
            embed.set_footer(text=f"Requested by {interaction.user.display_name}")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in serverinfo command: {e}")
            await interaction.response.send_message(
                "Failed to get server information.",
                ephemeral=True
            )
    
    @app_commands.command(name="userinfo", description="Show information about a user")
    @app_commands.describe(user="The user to get information about")
    async def user_info(
        self, 
        interaction: discord.Interaction, 
        user: Optional[discord.Member] = None
    ):
        """Display user information."""
        try:
            if not await self.bot.feature_manager.is_enabled(interaction.guild.id, "general"):
                return await interaction.response.send_message(
                    self.personality.get("general", "feature_disabled"),
                    ephemeral=True
                )
            
            target = user or interaction.user
            
            embed = discord.Embed(
                title=f"User Info: {target.display_name}",
                color=target.color if target.color != discord.Color.default() else discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            # Basic user info
            embed.add_field(
                name="👤 User Details",
                value=(
                    f"**Username:** {target.name}\n"
                    f"**Display Name:** {target.display_name}\n"
                    f"**ID:** `{target.id}`\n"
                    f"**Created:** <t:{int(target.created_at.timestamp())}:R>"
                ),
                inline=True
            )
            
            # Server-specific info
            embed.add_field(
                name="🏠 Server Details",
                value=(
                    f"**Joined:** <t:{int(target.joined_at.timestamp())}:R>\n"
                    f"**Status:** {target.status.name.title()}\n"
                    f"**Top Role:** {target.top_role.mention}\n"
                    f"**Roles:** {len(target.roles) - 1}"  # -1 to exclude @everyone
                ),
                inline=True
            )
            
            # Permissions check
            is_admin = target.guild_permissions.administrator
            is_bot_admin = await self.bot.admin_manager.is_bot_admin(target)
            
            permissions = []
            if target.guild_permissions.administrator:
                permissions.append("Administrator")
            if is_bot_admin:
                permissions.append("Bot Admin")
            if target.guild_permissions.manage_guild:
                permissions.append("Manage Server")
            if target.guild_permissions.manage_messages:
                permissions.append("Manage Messages")
            
            if permissions:
                embed.add_field(
                    name="🔑 Key Permissions",
                    value="\n".join([f"• {perm}" for perm in permissions]),
                    inline=False
                )
            
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.set_footer(text=f"Requested by {interaction.user.display_name}")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in userinfo command: {e}")
            await interaction.response.send_message(
                "Failed to get user information.",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(General(bot))