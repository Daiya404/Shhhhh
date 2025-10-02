# main.py
import logging
from datetime import datetime
import asyncio
import random
import discord  # <-- THIS IS THE FIX

from config.settings import settings
from config.personalities import get_console_message
from core.bot import TikaBot
from core.logging_formatter import TikaFormatter


def setup_logging():
    """Sets up logging with Tika's personality."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = TikaFormatter()

    log_dir = settings.LOGS_DIR
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = f"{timestamp}.log"

    file_handler = logging.FileHandler(
        filename=log_dir / log_filename,
        encoding='utf-8',
        mode='w'
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger


async def main():
    """The main function to initialize and run the bot."""
    logger = setup_logging()

    logger.info(get_console_message("startup.booting"))

    if not settings.TOKEN:
        logger.critical(get_console_message("startup.token_fail"))
        return

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    bot = TikaBot(intents=intents)

    try:
        await bot.start(settings.TOKEN)
    except discord.LoginFailure:
        logger.critical(get_console_message("startup.login_fail"))
    except Exception as e:
        logger.critical(get_console_message("startup.unexpected_fail"), exc_info=e)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(get_console_message("shutdown.request"))