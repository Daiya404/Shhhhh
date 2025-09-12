# main.py
import discord
import asyncio
import logging
from config.settings import settings
from core.bot import TikaBot

def setup_logging():
    logger = logging.getLogger('discord')
    logger.setLevel(logging.INFO)
    logging.getLogger('discord.http').setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
    
    # Ensure logs directory exists
    log_dir = settings.LOGS_DIR
    log_dir.mkdir(exist_ok=True)
    
    file_handler = logging.FileHandler(filename=log_dir / 'bot.log', encoding='utf-8', mode='w')
    file_handler.setFormatter(formatter)
    
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger

async def main():
    logger = setup_logging()
    # This line is changed
    if not settings.TOKEN:
        logger.critical("`token.txt` not found or is empty. I can't start without it.")
        return

    bot = TikaBot(settings=settings)
    
    try:
        await bot.start(settings.TOKEN)
    except discord.LoginFailure:
        # This line is changed
        logger.critical("Invalid token in `token.txt`. Check that you copied it correctly.")
    except Exception as e:
        logger.critical("An unexpected error occurred during startup:", exc_info=e)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot shutdown requested. Fine, I'll go.")