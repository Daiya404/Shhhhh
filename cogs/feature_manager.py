# cogs/feature_manager.py
import discord
from discord.ext import commands
from discord import option
from .bot_admin import is_bot_admin

AVAILABLE_FEATURES = [
    "bot_admin",
    "feature_manager",
]

class FeatureManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.feature_cache: dict[str, dict[str, bool]] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        """Load feature settings from file into the cache when the bot starts."""
        self.feature_cache = await self.bot.data_manager.get_data("feature_toggles")
        # The loading message in tika.py is sufficient. No need for extra console chatter.

    def is_feature_enabled(self, guild_id: int, feature_name: str) -> bool:
        guild_settings = self.feature_cache.get(str(guild_id), {})
        return guild_settings.get(feature_name, True)

    async def feature_autocomplete(self, ctx: discord.AutocompleteContext) -> list[str]:
        return [feature for feature in AVAILABLE_FEATURES if feature.startswith(ctx.value.lower())]

    @commands.slash_command(
        name="feature",
        description="Enable or disable bot features for this server.",
        checks=[is_bot_admin()]
    )
    @option("feature", description="The feature to manage.", autocomplete=feature_autocomplete)
    @option("state", description="The new state for the feature.", choices=["On", "Off"])
    async def feature_manager(self, ctx: discord.ApplicationContext, feature: str, state: str):
        if feature not in AVAILABLE_FEATURES:
            return await ctx.respond("That's not a valid feature. Pay attention.", ephemeral=True)

        guild_id_str = str(ctx.guild.id)
        new_state_bool = (state == "On")

        if guild_id_str not in self.feature_cache:
            self.feature_cache[guild_id_str] = {}
        self.feature_cache[guild_id_str][feature] = new_state_bool

        await self.bot.data_manager.save_data("feature_toggles", self.feature_cache)

        state_text = "ENABLED" if new_state_bool else "DISABLED"
        feature_text = feature.replace('_', ' ').title()
        await ctx.respond(f"Fine. The **{feature_text}** feature is now **{state_text}**.")

def setup(bot):
    bot.add_cog(FeatureManager(bot))