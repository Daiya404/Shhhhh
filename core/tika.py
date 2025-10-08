# core/tika.py
import discord
import logging

from config import COGS_DIR
from services.data_manager import DataManager

logger = logging.getLogger(__name__)

class TikaBot(discord.Bot):
    """The main bot class for Tika."""

    def __init__(self, data_manager: DataManager):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(intents=intents)
        self.data_manager = data_manager
        
        # A flag to ensure we only sync commands once, not on every reconnect.
        self._commands_synced = False

    def initialize_cogs(self):
        """
        Our new, focused function. Its only job is to load cogs.
        This is called manually from main.py before the bot logs in.
        """
        logger.info("System boot initiated. Acknowledging cogs...")
        
        loaded_cogs = 0
        for file in COGS_DIR.glob("*.py"):
            if not file.name.startswith("_"):
                try:
                    self.load_extension(f"cogs.{file.stem}")
                    logger.info(f" -> Cog '{file.stem}' loaded. As expected.")
                    loaded_cogs += 1
                except Exception as e:
                    logger.warning(f" -> Hmph. Failed to load '{file.stem}'. Details:\n   {e}")
        
        logger.info(f"Cog integration complete. {loaded_cogs} modules active.")

    async def on_ready(self):
        """
        Called when the bot is fully connected. This is the correct place to sync commands.
        """
        print("-" * 30)
        logger.info("Connection to Discord established.")
        
        # Sync commands only on the first on_ready event.
        if not self._commands_synced:
            try:
                await self.sync_commands()
                logger.info("Application commands synced with Discord.")
                self._commands_synced = True
            except Exception as e:
                logger.error(f"Failed to sync application commands. Details: {e}")

        logger.info(f"Identity confirmed: {self.user} (ID: {self.user.id})")
        logger.info("System online. Awaiting instructions.")
        print("-" * 30)