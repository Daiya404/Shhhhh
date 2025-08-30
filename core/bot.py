import discord
from discord.ext import commands
import logging
from collections import defaultdict
from pathlib import Path

from shared.database.manager import DataManager
from .plugin_manager import PluginManager

class TikaBot(commands.Bot):
    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger("TikaBot")
        
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True

        super().__init__(
            command_prefix="!", # Will be replaced by a smart router
            intents=intents,
            help_command=None
        )
        
        # Core Services
        self.data_manager = DataManager()
        self.plugin_manager = PluginManager(self)
        self.plugin_configs = self.config.get('plugins', {})
        
        # Enhanced Frustration/Personality Tracker
        self.command_usage = defaultdict(lambda: defaultdict(list))

    async def setup_hook(self):
        """The entry point for bot setup."""
        self.logger.info("--- Tika PEAK Architecture is waking up... ---")
        
        # Load all plugins
        await self.plugin_manager.load_plugins()
        
        # Sync application commands
        try:
            synced = await self.tree.sync()
            self.logger.info(f"🔄 Synced {len(synced)} application command(s).")
        except Exception as e:
            self.logger.error(f"Failed to sync application commands: {e}")

    async def on_ready(self):
        self.logger.info(f"---")
        self.logger.info(f"Logged in as: {self.user} (ID: {self.user.id})")
        self.logger.info(f"Serving {len(self.guilds)} server(s).")
        self.logger.info(f"Discord.py Version: {discord.__version__}")
        self.logger.info(f"--- Tika is now online and ready! ---")

    async def on_message(self, message: discord.Message):
        """
        This will be replaced by the Smart Message Router.
        For now, it just routes to plugins.
        """
        if message.author.bot:
            return

        # Simple routing through loaded plugins in order
        for plugin in self.plugin_manager.get_loaded_plugins():
            if await plugin.on_message(message):
                # If a plugin returns True, it means the message is handled.
                return
        
        # If no plugin handles it, process traditional commands (for now)
        await self.process_commands(message)