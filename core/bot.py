# core/bot.py
import discord
from discord.ext import commands
import logging
from config.settings import Settings
from services.data_manager import DataManager
from collections import defaultdict

class TikaBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True
        super().__init__(command_prefix=settings.COMMAND_PREFIX, intents=intents, help_command=None)
        
        self.settings = settings
        self.logger = logging.getLogger('discord')
        self.command_usage = defaultdict(lambda: defaultdict(list))
        # Initialize Services
        self.data_manager = DataManager(base_path=self.settings.DATA_DIR)

    async def setup_hook(self):
        self.logger.info("--- Tika is waking up... ---")
        
        # Create essential directories
        self.settings.DATA_DIR.mkdir(exist_ok=True)
        self.settings.LOGS_DIR.mkdir(exist_ok=True)

        # Load Cogs
        loaded_cogs = 0
        for folder in self.settings.COGS_DIR.iterdir():
            if folder.is_dir():
                for file in folder.glob("*.py"):
                    if not file.name.startswith("_"):
                        try:
                            extension = f"cogs.{folder.name}.{file.stem}"
                            await self.load_extension(extension)
                            self.logger.info(f"✅ Loaded Cog: {extension}")
                            loaded_cogs += 1
                        except Exception as e:
                            self.logger.error(f"❌ Failed to load Cog: {extension}", exc_info=e)
        self.logger.info(f"--- Loaded {loaded_cogs} cog(s) successfully. ---")

        # Sync application commands
        synced = await self.tree.sync()
        self.logger.info(f"🔄 Synced {len(synced)} application command(s) globally.")

    async def on_ready(self):
        self.logger.info("---")
        self.logger.info(f"Logged in as: {self.user} (ID: {self.user.id})")
        self.logger.info(f"Serving {len(self.guilds)} server(s).")
        self.logger.info(f"Discord.py Version: {discord.__version__}")
        self.logger.info(f"--- Tika is now online and ready! ---")