import discord
from discord.ext import commands
import logging
from pathlib import Path
import asyncio
from collections import defaultdict

# --- Logging Setup ---
logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
logging.getLogger('discord.http').setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
file_handler = logging.FileHandler(filename='bot.log', encoding='utf-8', mode='w')
file_handler.setFormatter(formatter)

logger.addHandler(stream_handler)
logger.addHandler(file_handler)


class TikaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True

        super().__init__(
            command_prefix=commands.when_mentioned_or('!'), # Fallback prefix
            intents=intents,
            help_command=None
        )
        self.logger = logger
        # This is the central data store for the Frustration Engine.
        # It will hold data like: {user_id: {command_name: [timestamp1, timestamp2]}}
        self.command_usage = defaultdict(lambda: defaultdict(list))

    async def setup_hook(self):
        """This is called when the bot first starts up."""
        self.logger.info(f"--- Tika is waking up... ---")
        
        # Ensure essential directories exist
        Path("data").mkdir(exist_ok=True)
        Path("cogs").mkdir(exist_ok=True)
        Path("utils").mkdir(exist_ok=True)

        # Dynamically load all cogs
        loaded_cogs = 0
        for cog_file in Path("cogs").glob("*.py"):
            if cog_file.name.startswith("_"): continue
            
            try:
                await self.load_extension(f"cogs.{cog_file.stem}")
                self.logger.info(f"✅ Loaded Cog: {cog_file.name}")
                loaded_cogs += 1
            except Exception as e:
                self.logger.error(f"❌ Failed to load Cog: {cog_file.name}", exc_info=e)
        
        self.logger.info(f"--- Loaded {loaded_cogs} cog(s) successfully. ---")

        # Sync application commands
        try:
            synced = await self.tree.sync()
            self.logger.info(f"🔄 Synced {len(synced)} application command(s).")
        except Exception as e:
            self.logger.error(f"Failed to sync application commands: {e}")

    async def on_ready(self):
        activity = discord.Game(name="Doing things. Perfectly, of course.")
        await self.change_presence(status=discord.Status.online, activity=activity)
        
        self.logger.info(f"---")
        self.logger.info(f"Logged in as: {self.user} (ID: {self.user.id})")
        self.logger.info(f"Serving {len(self.guilds)} server(s).")
        self.logger.info(f"Discord.py Version: {discord.__version__}")
        self.logger.info(f"--- Tika is now online and ready! ---")


async def main():
    token_file = Path("token.txt")
    if not token_file.exists() or not token_file.read_text().strip():
        logger.critical("`token.txt` not found or is empty. Please create it and paste your bot token inside.")
        return

    token = token_file.read_text().strip()
    bot = TikaBot()
    
    try:
        await bot.start(token)
    except discord.LoginFailure:
        logger.critical("Invalid token in `token.txt`. Check that you copied it correctly.")
    except Exception as e:
        logger.critical(f"An unexpected error occurred during startup:", exc_info=e)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested.")