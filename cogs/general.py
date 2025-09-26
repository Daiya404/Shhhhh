# cogs/general.py
import discord
from discord.ext import commands
from discord import app_commands

from core.personality import PERSONALITY

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.p = PERSONALITY["hello"]

    @app_commands.command(name="hello", description="A simple test command.")
    async def hello(self, interaction: discord.Interaction):
        """This is a simple command that says hello."""
        
        # Check if the feature is enabled for this server
        if not await self.bot.feature_manager.is_enabled(interaction.guild.id, "general"):
            # You can send a silent error or a visible one
            return await interaction.response.send_message("This feature is disabled.", ephemeral=True)

        # Example of using the personality file
        # This could be expanded to check if the user is a "friend"
        await interaction.response.send_message(self.p["response"])

async def setup(bot):
    await bot.add_cog(General(bot))