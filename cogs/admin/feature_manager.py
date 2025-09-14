# cogs/admin/feature_manager.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Dict, Optional

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

AVAILABLE_FEATURES = [
    # Admin
    "clear_commands",       # /clear and /clearsearch
    "detention_system",
    # Fun
    "fun_commands",         # /coinflip, /roll, /rps, /8ball
    "server_games",         # /play (tictactoe, connect4, etc.)
    "word_game",
    # Moderation
    "auto_reply",
    "word_blocker",
    "link_fixer",
    # Utility
    "copy_chapel",
    "custom_roles",
    "reminders",
    # AI
    "ai_chat"
]

class FeatureManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.data_manager = self.bot.data_manager
        # In-memory cache for feature toggles for instant checks
        self.feature_settings_cache: Dict[str, Dict[str, bool]] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        """Loads feature toggle settings into memory."""
        self.logger.info("Loading feature toggle settings into memory...")
        self.feature_settings_cache = await self.data_manager.get_data("feature_toggles")
        self.logger.info("Feature toggle settings cache is ready.")

    def is_feature_enabled(self, guild_id: int, feature_name: str) -> bool:
        """A quick, synchronous check to see if a feature is enabled for a guild."""
        guild_settings = self.feature_settings_cache.get(str(guild_id), {})
        # Features are enabled by default if no setting is found.
        return guild_settings.get(feature_name, True)

    @app_commands.command(name="feature-manager", description="[Admin] Enable or disable bot features for this server.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        feature="The feature you want to enable or disable.",
        state="The new state for the feature."
    )
    @app_commands.choices(
        feature=[app_commands.Choice(name=name.replace('_', ' ').title(), value=name) for name in AVAILABLE_FEATURES],
        state=[app_commands.Choice(name="On", value="on"), app_commands.Choice(name="Off", value="off")]
    )
    async def feature_manager(self, interaction: discord.Interaction, feature: str, state: str):
        await interaction.response.defer() # Public response for admin transparency
        
        guild_id = str(interaction.guild_id)
        guild_settings = self.feature_settings_cache.setdefault(guild_id, {})
        
        new_state_bool = (state == "on")
        guild_settings[feature] = new_state_bool
        
        await self.data_manager.save_data("feature_toggles", self.feature_settings_cache)
        
        state_text = "ENABLED" if new_state_bool else "DISABLED"
        await interaction.followup.send(f"Fine. The **{feature.replace('_', ' ').title()}** feature is now **{state_text}** for this server.")

async def setup(bot):
    await bot.add_cog(FeatureManager(bot))