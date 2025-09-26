# cogs/admin.py
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

class Admin(commands.Cog):
    """Administrative commands for bot management."""
    
    def __init__(self, bot):
        self.bot = bot
        self.personality = bot.personality
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure user has admin permissions for all commands in this cog."""
        try:
            is_admin = await self.bot.admin_manager.is_bot_admin(interaction.user)
            if not is_admin:
                await interaction.response.send_message(
                    self.personality.get("general", "permission_denied"),
                    ephemeral=True
                )
                logger.warning(f"Admin command denied for {interaction.user} in {interaction.guild}")
            return is_admin
        except Exception as e:
            logger.error(f"Error in admin interaction check: {e}")
            return False
    
    # Bot Admin Management Commands
    botadmin = app_commands.Group(
        name="botadmin", 
        description="Manage who can use bot admin commands"
    )
    
    @botadmin.command(name="add", description="Add a delegated bot admin")
    @app_commands.describe(user="The user to add as a bot admin")
    async def add_admin(self, interaction: discord.Interaction, user: discord.Member):
        """Add a user as a bot admin."""
        try:
            # Check if user is already an admin
            if await self.bot.admin_manager.is_bot_admin(user):
                return await interaction.response.send_message(
                    self.personality.get("admin", "already_admin"),
                    ephemeral=True
                )
            
            # Add the admin
            success = await self.bot.admin_manager.add_admin(interaction.guild.id, user.id)
            if success:
                await interaction.response.send_message(
                    self.personality.get("admin", "admin_added", user=user.display_name)
                )
                logger.info(f"Added admin {user} to guild {interaction.guild}")
            else:
                await interaction.response.send_message(
                    self.personality.get("admin", "already_admin"),
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            await interaction.response.send_message(
                "An error occurred while adding the admin.",
                ephemeral=True
            )
    
    @botadmin.command(name="remove", description="Remove a delegated bot admin")
    @app_commands.describe(user="The user to remove from bot admins")
    async def remove_admin(self, interaction: discord.Interaction, user: discord.Member):
        """Remove a user from bot admins."""
        try:
            success = await self.bot.admin_manager.remove_admin(interaction.guild.id, user.id)
            if success:
                await interaction.response.send_message(
                    self.personality.get("admin", "admin_removed", user=user.display_name)
                )
                logger.info(f"Removed admin {user} from guild {interaction.guild}")
            else:
                await interaction.response.send_message(
                    self.personality.get("admin", "not_admin"),
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            await interaction.response.send_message(
                "An error occurred while removing the admin.",
                ephemeral=True
            )
    
    @botadmin.command(name="list", description="List all delegated bot admins")
    async def list_admins(self, interaction: discord.Interaction):
        """List all bot admins for the current guild."""
        try:
            admin_ids = await self.bot.admin_manager.get_all_admins(interaction.guild.id)
            
            if not admin_ids:
                return await interaction.response.send_message(
                    self.personality.get("admin", "no_admins"),
                    ephemeral=True
                )
            
            embed = discord.Embed(
                title=self.personality.get("admin", "list_admins_title"),
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            # Get user mentions, handle cases where users might not be found
            admin_mentions = []
            for user_id in admin_ids:
                user = interaction.guild.get_member(user_id)
                if user:
                    admin_mentions.append(f"• {user.mention} (`{user.display_name}`)")
                else:
                    admin_mentions.append(f"• <@{user_id}> (User not found)")
            
            embed.description = "\n".join(admin_mentions)
            embed.set_footer(text=f"Total: {len(admin_ids)} admin(s)")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error listing admins: {e}")
            await interaction.response.send_message(
                "An error occurred while listing admins.",
                ephemeral=True
            )
    
    # Feature Management Commands
    feature = app_commands.Group(
        name="feature",
        description="Enable or disable bot features for this server"
    )
    
    @feature.command(name="toggle", description="Enable or disable a feature")
    @app_commands.describe(
        feature="The feature to toggle",
        action="Whether to enable or disable the feature"
    )
    async def toggle_feature(
        self, 
        interaction: discord.Interaction, 
        feature: str, 
        action: str
    ):
        """Toggle a feature on or off."""
        try:
            # Validate feature exists
            if feature not in self.bot.feature_manager.available_features:
                return await interaction.response.send_message(
                    self.personality.get("feature", "feature_not_found", feature=feature),
                    ephemeral=True
                )
            
            # Validate action
            if action.lower() not in ["enable", "disable"]:
                return await interaction.response.send_message(
                    "Action must be either 'enable' or 'disable'.",
                    ephemeral=True
                )
            
            guild_id = interaction.guild.id
            is_enabled = await self.bot.feature_manager.is_enabled(guild_id, feature)
            
            if action.lower() == "enable":
                if is_enabled:
                    return await interaction.response.send_message(
                        self.personality.get("feature", "already_enabled"),
                        ephemeral=True
                    )
                
                await self.bot.feature_manager.enable_feature(guild_id, feature)
                message = self.personality.get("feature", "feature_enabled", feature=feature)
                
            else:  # disable
                if not is_enabled:
                    return await interaction.response.send_message(
                        self.personality.get("feature", "already_disabled"),
                        ephemeral=True
                    )
                
                await self.bot.feature_manager.disable_feature(guild_id, feature)
                message = self.personality.get("feature", "feature_disabled", feature=feature)
            
            await interaction.response.send_message(message)
            
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
        except Exception as e:
            logger.error(f"Error toggling feature: {e}")
            await interaction.response.send_message(
                "An error occurred while toggling the feature.",
                ephemeral=True
            )
    
    @toggle_feature.autocomplete('feature')
    async def feature_autocomplete(
        self, 
        interaction: discord.Interaction, 
        current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for feature names."""
        features = self.bot.feature_manager.available_features
        return [
            app_commands.Choice(name=feature, value=feature)
            for feature in features
            if current.lower() in feature.lower()
        ][:25]  # Discord limits to 25 choices
    
    @toggle_feature.autocomplete('action')
    async def action_autocomplete(
        self, 
        interaction: discord.Interaction, 
        current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for enable/disable actions."""
        choices = [
            app_commands.Choice(name="Enable", value="enable"),
            app_commands.Choice(name="Disable", value="disable")
        ]
        return [choice for choice in choices if current.lower() in choice.name.lower()]
    
    @feature.command(name="list", description="List the status of all available features")
    async def list_features(self, interaction: discord.Interaction):
        """List all features and their current status."""
        try:
            feature_status = await self.bot.feature_manager.get_feature_status(interaction.guild.id)
            
            if not feature_status:
                return await interaction.response.send_message(
                    "No features are available.",
                    ephemeral=True
                )
            
            embed = discord.Embed(
                title=self.personality.get("feature", "list_features_title"),
                color=discord.Color.purple(),
                timestamp=discord.utils.utcnow()
            )
            
            # Group features by status for better readability
            enabled_features = [f for f, enabled in feature_status.items() if enabled]
            disabled_features = [f for f, enabled in feature_status.items() if not enabled]
            
            if enabled_features:
                embed.add_field(
                    name="✅ Enabled Features",
                    value="\n".join([f"• `{feature}`" for feature in sorted(enabled_features)]),
                    inline=False
                )
            
            if disabled_features:
                embed.add_field(
                    name="❌ Disabled Features",
                    value="\n".join([f"• `{feature}`" for feature in sorted(disabled_features)]),
                    inline=False
                )
            
            embed.set_footer(
                text=f"Total: {len(enabled_features)} enabled, {len(disabled_features)} disabled"
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error listing features: {e}")
            await interaction.response.send_message(
                "An error occurred while listing features.",
                ephemeral=True
            )
    
    @feature.command(name="reset", description="Reset all features to default (enabled)")
    async def reset_features(self, interaction: discord.Interaction):
        """Reset all features to their default state."""
        try:
            await self.bot.feature_manager.reset_guild_features(interaction.guild.id)
            
            embed = discord.Embed(
                title="Features Reset",
                description="All features have been reset to their default state (enabled).",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error resetting features: {e}")
            await interaction.response.send_message(
                "An error occurred while resetting features.",
                ephemeral=True
            )
    
    # Bot Information and Status Commands
    @app_commands.command(name="botstatus", description="Show bot status and information")
    async def show_bot_status(self, interaction: discord.Interaction):
        """Display bot status information."""
        try:
            embed = discord.Embed(
                title="Bot Status",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            # Basic bot info
            embed.add_field(
                name="Bot Information",
                value=(
                    f"**Name:** {self.bot.user.display_name}\n"
                    f"**ID:** {self.bot.user.id}\n"
                    f"**Servers:** {len(self.bot.guilds)}\n"
                    f"**Users:** {sum(guild.member_count for guild in self.bot.guilds)}"
                ),
                inline=True
            )
            
            # Feature information
            feature_count = len(self.bot.feature_manager.available_features)
            enabled_count = sum(
                1 for feature in self.bot.feature_manager.available_features
                if await self.bot.feature_manager.is_enabled(interaction.guild.id, feature)
            )
            
            embed.add_field(
                name="Features",
                value=(
                    f"**Available:** {feature_count}\n"
                    f"**Enabled:** {enabled_count}\n"
                    f"**Disabled:** {feature_count - enabled_count}"
                ),
                inline=True
            )
            
            # Admin information
            admin_count = len(await self.bot.admin_manager.get_all_admins(interaction.guild.id))
            embed.add_field(
                name="This Server",
                value=(
                    f"**Bot Admins:** {admin_count}\n"
                    f"**Guild ID:** {interaction.guild.id}"
                ),
                inline=True
            )
            
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            embed.set_footer(text="Use /help for available commands")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error getting bot status: {e}")
            await interaction.response.send_message(
                "An error occurred while getting bot status.",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Admin(bot))