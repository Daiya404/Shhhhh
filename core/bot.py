import discord
from discord.ext import commands
import os
import logging
from pathlib import Path

# --- Core Imports ---
from core.personalities import PERSONALITY_RESPONSES

# --- Service Imports ---
from services.data_manager import DataManager
from services.frustration_manager import FrustrationManager
from services.backup_service import BackupService

class TikaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        
        self.root_dir = Path(__file__).parent.parent

        super().__init__(command_prefix="tika!", intents=intents, help_command=None)

        # --- Setup Logging ---
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s: %(message)s')
        self.logger = logging.getLogger('TikaBot')

        # --- Load Core Components & Secrets ---
        # SIMPLIFIED: Attach the personality dictionary directly to the bot instance.
        self.personalities = PERSONALITY_RESPONSES
        self.secrets = self._load_secrets()

        if not self.secrets.get("discord_token"):
            self.logger.critical("CRITICAL: discord_token.txt not found in /secrets. The bot cannot start.")
            exit()

    def _load_secrets(self) -> dict:
        """Loads all secrets from the secrets/ directory."""
        secrets_dir = self.root_dir / "secrets"
        secrets = {}
        if not secrets_dir.exists():
            self.logger.critical(f"CRITICAL: secrets folder not found!")
            return {}
        for filename in os.listdir(secrets_dir):
            if filename.endswith(".txt"):
                try:
                    with open(secrets_dir / filename, 'r', encoding='utf-8') as f:
                        key = filename[:-4]
                        secrets[key] = f.read().strip()
                except Exception as e:
                    self.logger.error(f"Error loading secret {filename}: {e}")
        return secrets

    async def _load_services(self):
        """Initializes and attaches services to the bot instance."""
        self.logger.info("Loading services...")
        self.data_manager = DataManager(self)
        self.frustration_manager = FrustrationManager(self)
        self.backup_service = BackupService(self)
        self.logger.info("All services loaded.")

    async def _load_cogs(self):
        """Dynamically loads all cogs from the cogs/ directory."""
        self.logger.info("Loading cogs...")
        cogs_dir = self.root_dir / "cogs"
        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                try:
                    cog_path = f'cogs.{filename[:-3]}'
                    await self.load_extension(cog_path)
                    self.logger.info(f"  -> Loaded cog: {cog_path}")
                except Exception as e:
                    self.logger.error(f"Failed to load cog {cog_path}: {e}", exc_info=True)
        self.logger.info("All cogs loaded.")

    async def setup_hook(self):
        """The main entry point for asynchronous setup before the bot connects."""
        await self._load_services()
        await self._load_cogs()

    async def on_ready(self):
        """Called when the bot is fully connected and ready."""
        self.logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        self.logger.info('------')

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        """Global listener to record all successful command usages."""
        if ctx.guild is None:  # Ignore DMs
            return
        self.frustration_manager.record_command_usage(ctx.author.id)

    def run(self):
        """Starts the bot using the token."""
        super().run(self.secrets["discord_token"], log_handler=None)