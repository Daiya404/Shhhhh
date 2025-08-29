# --- main.py ---
import discord
import asyncio
import logging
import os
from pathlib import Path
import yaml # Requires PyYAML
from dotenv import load_dotenv # Requires python-dotenv

from core.bot import TikaBot

# --- Setup Logging ---
def setup_logging(config: dict):
    log_config = config.get('logging', {})
    level = getattr(logging, log_config.get('level', 'INFO').upper(), logging.INFO)
    
    logger = logging.getLogger()
    logger.setLevel(level)
    
    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
    
    # Stream Handler (Console)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    
    # File Handler
    file_handler = logging.FileHandler(
        filename=log_config.get('file', 'bot.log'),
        encoding='utf-8',
        mode='w'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

async def main():
    # --- Load Config and Secrets ---
    try:
        with open("config.yml", 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logging.critical("`config.yml` not found. Please create it.")
        return

    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logging.critical("`DISCORD_TOKEN` not found in .env file. Please create it.")
        return
        
    setup_logging(config)
    
    bot = TikaBot(config)

    try:
        await bot.start(token)
    except discord.LoginFailure:
        logging.critical("Invalid token. Please check your .env file.")
    except Exception as e:
        logging.critical("An unexpected error occurred during startup:", exc_info=e)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot shutdown requested.")