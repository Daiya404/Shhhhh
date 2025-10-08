# cogs/feature_manager.py
import discord
from discord.ext import commands
from discord import option
from utils.checks import is_bot_admin # <-- IMPORT FROM THE NEW LOCATION

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
        self.feature_cache = await self.bot.data_manager.get_data("feature_toggles")

    def is_feature_enabled(self, guild_id: int, feature_name: str) -> bool:
        guild_settings = self.feature_cache.get(str(guild_id), {})
        return guild_settings.get(feature_name, True)

    async def feature_autocomplete(self, ctx: discord.AutocompleteContext) -> list[str]:
        return [feature for feature in AVAILABLE_FEATURES if feature.startswith(ctx.value.lower())]

    @commands.slash_command(name="feature", description="Enable or disable bot features for this server.")
    @commands.check(is_bot_admin) # We use our check as a decorator here
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
        await ctx.respond(f"Fine. The **{feature_text}** feature is now **{state_text}**.", ephemeral=True)
    
    # Add an error handler for the check
    async def cog_command_error(self, ctx: discord.ApplicationContext, error: discord.DiscordException):
        if isinstance(error, commands.CheckFailure):
            await ctx.respond("You don't have permission to do that.", ephemeral=True)
        else:
            # For other errors, we can log them or send a generic message
            print(f"An unhandled error occurred in FeatureManager: {error}")
            await ctx.respond("Something went wrong on my end.", ephemeral=True)

def setup(bot):
    bot.add_cog(FeatureManager(bot))