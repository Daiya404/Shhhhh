# main.py
import asyncio
import sys
import logging
from pathlib import Path

def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def check_requirements():
    """Check if all required files and directories exist."""
    required_dirs = ['cogs', 'services', 'core', 'data', 'secrets']
    required_files = ['requirements.txt']
    
    for directory in required_dirs:
        Path(directory).mkdir(exist_ok=True)
    
    for file in required_files:
        if not Path(file).exists():
            print(f"Warning: {file} not found")

async def main():
    """Main function to initialize and run the bot."""
    setup_logging()
    check_requirements()
    
    try:
        from core.bot import TikaBot
        from core.secrets_loader import load_secrets
        
        # Load secrets
        secrets = load_secrets()
        token = secrets.get("token")
        
        if not token:
            logging.error("Bot token not found. Please add token.txt to the secrets directory.")
            sys.exit(1)
        
        # Initialize and run bot
        async with TikaBot(secrets=secrets) as bot:
            await bot.start(token)
            
    except KeyboardInterrupt:
        logging.info("Bot shutdown requested by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")