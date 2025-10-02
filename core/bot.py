# core/bot.py
import discord
import logging

from config.settings import settings
from config.personalities import get_console_message


class TikaBot(discord.Bot):
    """
    The core bot class for Tika.
    """

    def __init__(self, *args, **kwargs):
        # This is the correct way to initialize the parent class.
        # It takes all arguments given to TikaBot (like 'intents')
        # and passes them directly to discord.Bot.
        super().__init__(*args, **kwargs)

        self.logger = logging.getLogger('discord')

        # We will initialize services here later
        # self.data_manager = ...
        # self.personality_service = ...

    async def on_ready(self):
        """Called when the bot is successfully connected to Discord."""
        self.logger.info("---")
        self.logger.info(get_console_message("on_ready.login", username=self.user, user_id=self.user.id))
        self.logger.info(get_console_message("on_ready.servers", count=len(self.guilds)))
        self.logger.info(get_console_message("on_ready.ready"))
        self.logger.info("---")

    async def setup_hook(self):
        """Called to load command cogs."""
        self.logger.info(get_console_message("cogs.loading"))

        loaded_cogs = 0

        # We'll add the real cog loading logic in the next steps

        self.logger.info(get_console_message("cogs.all_loaded", count=loaded_cogs))