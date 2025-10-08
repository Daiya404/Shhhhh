# main.py
import sys
import discord
import logging
import asyncio

from config import BOT_TOKEN, DATA_DIR
from services.data_manager import DataManager
from core.tika import TikaBot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [ TikaOS ] %(message)s',
    datefmt='%H:%M:%S'
)
logging.getLogger('discord.http').setLevel(logging.WARNING)
logging.getLogger('discord.gateway').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

async def main():
    if not BOT_TOKEN:
        logger.critical("FATAL: Bot Token not found in .env file. I can't start without it.")
        sys.exit(1)

    data_manager = DataManager(data_directory=DATA_DIR)
    bot = TikaBot(data_manager=data_manager)

    try:
        # We now call the function that ONLY loads cogs.
        bot.initialize_cogs()
        
        await bot.start(BOT_TOKEN)
        
    except discord.LoginFailure:
        logger.critical("FATAL: Invalid token. Check that you copied it correctly.")
    except Exception as e:
        logger.critical(f"An unexpected error occurred during startup: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())