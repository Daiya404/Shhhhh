import discord
from discord.ext import commands
from discord import app_commands
import logging
from core.personalities import PERSONALITY_RESPONSES

# A list of all available features in your bot.
# This MUST be updated when you add a new feature cog.
AVAILABLE_FEATURES = [
    "chapel_system", "detention_system", "word_game", "custom_roles",
    "reminders", "fun_commands", "word_blocker", "auto_reply",
    "link_fixer", "server_games", "clear_commands"
]

class FeatureManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["feature_manager"]
        self.data_manager = self.bot.data_manager
        self.config_cache = {}

    @commands.Cog.listener()
    async def on_ready(self):
        self.config_cache = await self.data_manager.get_data("server_config")

    def _get_feature_settings(self, guild_id: int) -> dict:
        """Helper to safely get the feature settings dictionary for a guild."""
        guild_config = self.config_cache.setdefault(str(guild_id), {})
        return guild_config.setdefault("features", {feature: True for feature in AVAILABLE_FEATURES})

    def is_feature_enabled(self, guild_id: int, feature_name: str) -> bool:
        """Checks if a specific feature is enabled for a guild."""
        if feature_name not in AVAILABLE_FEATURES:
            return False
        settings = self._get_feature_settings(guild_id)
        return settings.get(feature_name, True) # Default to True if not set

    @app_commands.command(name="features", description="Toggle bot features on or off for this server.")
    @app_commands.describe(action="List all features or toggle a specific one.", feature="The feature to toggle.")
    @app_commands.choices(action=[
        app_commands.Choice(name="List", value="list"),
        app_commands.Choice(name="Toggle", value="toggle")
    ])
    async def features(self, interaction: discord.Interaction, action: str, feature: str = None):
        bot_admin_cog = self.bot.get_cog("BotAdmin")
        if not bot_admin_cog or not await bot_admin_cog.is_user_bot_admin(interaction.user):
            await interaction.response.send_message("You don't have permission to manage features.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        settings = self._get_feature_settings(interaction.guild.id)
        
        if action == "toggle":
            if not feature or feature.lower() not in AVAILABLE_FEATURES:
                await interaction.followup.send(self.personality["invalid_feature"])
                return
            
            feature_key = feature.lower()
            current_state = settings.get(feature_key, True)
            settings[feature_key] = not current_state
            await self.data_manager.save_data("server_config", self.config_cache)

            response = self.personality["feature_enabled"] if settings[feature_key] else self.personality["feature_disabled"]
            await interaction.followup.send(response.format(feature=feature_key))

        elif action == "list":
            embed = discord.Embed(title=self.personality["list_title"], color=discord.Color.orange())
            for feat in sorted(AVAILABLE_FEATURES):
                status = self.personality["list_enabled"] if settings.get(feat, True) else self.personality["list_disabled"]
                embed.add_field(name=feat.replace("_", " ").title(), value=status, inline=True)
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(FeatureManager(bot))