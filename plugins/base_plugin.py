# --- plugins/base_plugin.py ---

from discord.ext import commands
import discord
import logging

class BasePlugin(commands.Cog):
    """
    The abstract base class for all Tika plugins.
    Ensures that every plugin follows a consistent structure.
    """
    def __init__(self, bot: commands.Bot):
        # We need to get the name before the logger is set up.
        # This will raise the NotImplementedError immediately if a subclass forgets it.
        plugin_name = self.name

        self.bot = bot
        self.logger = logging.getLogger(f"plugins.{plugin_name}")
        self.db = bot.data_manager # Access the unified data manager
        self.config = bot.plugin_configs.get(plugin_name, {})

    @property
    def name(self) -> str:
        """
        The unique, machine-readable name of the plugin.
        This MUST be implemented by every subclass.
        """
        raise NotImplementedError(f"Plugin {self.__class__.__name__} must have a 'name' property.")

    async def on_message(self, message: discord.Message) -> bool:
        """
        Optional message handler for the plugin.

        Args:
            message: The discord.Message object.

        Returns:
            True if the message was handled and processing should stop.
            False if processing should continue to the next plugin.
        """
        return False