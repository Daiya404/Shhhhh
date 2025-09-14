# main.py
import discord
import asyncio
import logging
from datetime import datetime
from config.settings import settings
from core.bot import TikaBot

def setup_logging():
    """Sets up logging to both the console and a timestamped file."""
    logger = logging.getLogger('discord')
    logger.setLevel(logging.INFO)
    logging.getLogger('discord.http').setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
    
    # 1. Ensure the main logs directory exists.
    log_dir = settings.LOGS_DIR
    log_dir.mkdir(exist_ok=True)
    
    # 2. Generate a filename based on the current date and time.
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = f"{timestamp}.log"
    
    # 3. Create the FileHandler with the new, unique filename.
    file_handler = logging.FileHandler(
        filename=log_dir / log_filename, 
        encoding='utf-8', 
        mode='w'
    )
    
    file_handler.setFormatter(formatter)
    
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    
    # Clear existing handlers to prevent duplicate logs on reconnects
    if logger.hasHandlers():
        logger.handlers.clear()
        
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    
    return logger

async def main():
    logger = setup_logging()
    if not settings.TOKEN:
        logger.critical("`token.txt` not found or is empty. I can't start without it.")
        return

    bot = TikaBot(settings=settings)
    
    try:
        await bot.start(settings.TOKEN)
    except discord.LoginFailure:
        logger.critical("Invalid token in `token.txt`. Check that you copied it correctly.")
    except Exception as e:
        logger.critical("An unexpected error occurred during startup:", exc_info=e)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot shutdown requested. Fine, I'll go.")