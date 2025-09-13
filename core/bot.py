# core/bot.py
import discord
from discord.ext import commands
import logging
from collections import defaultdict
import aiohttp

from config.settings import Settings
from services.data_manager import DataManager

class TikaBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True
        super().__init__(command_prefix=settings.COMMAND_PREFIX, intents=intents, help_command=None)
        
        self.settings = settings
        self.logger = logging.getLogger('discord')
        
        # Initialize Services
        self.data_manager = DataManager(base_path=self.settings.DATA_DIR)
        # Add the shared web session for making API calls
        self.http_session = aiohttp.ClientSession()
        
        self.command_usage = defaultdict(lambda: defaultdict(list))

    async def close(self):
        """Cleanly closes the bot and its services."""
        await super().close()
        await self.http_session.close()

    async def setup_hook(self):
        """Initializes the bot, loads cogs, and syncs commands."""
        self.logger.info("--- Tika is waking up... ---")
        self.settings.DATA_DIR.mkdir(exist_ok=True)
        self.settings.LOGS_DIR.mkdir(exist_ok=True)

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
        
        synced = await self.tree.sync()
        self.logger.info(f"🔄 Synced {len(synced)} application command(s) globally.")

    async def on_message(self, message: discord.Message):
        """The Traffic Cop: Checks every message and enforces high-priority rules."""
        if message.author.bot:
            return

        # Priority 1: Detention
        detention_cog = self.get_cog("Detention")
        if detention_cog and await detention_cog.is_user_detained(message):
            await detention_cog.handle_detention_message(message)
            return

        # Priority 2: Word Blocker
        word_blocker_cog = self.get_cog("WordBlocker")
        if word_blocker_cog and await word_blocker_cog.check_and_handle_message(message):
            return

        # Priority 3: Link Fixer (Does not stop processing)
        link_fixer_cog = self.get_cog("LinkFixer")
        if link_fixer_cog:
            await link_fixer_cog.check_and_fix_link(message)

        # Priority 4: Auto Reply
        auto_reply_cog = self.get_cog("AutoReply")
        if auto_reply_cog and await auto_reply_cog.check_for_reply(message):
            return

        ctx = await self.get_context(message)
        if ctx.valid:
            await self.invoke(ctx)
            
    async def on_ready(self):
        """Called when the bot is ready and online."""
        activity = discord.Game(name="Doing things. Perfectly, of course.")
        await self.change_presence(status=discord.Status.online, activity=activity)
        self.logger.info("---")
        self.logger.info(f"Logged in as: {self.user} (ID: {self.user.id})")
        self.logger.info(f"Serving {len(self.guilds)} server(s).")
        self.logger.info(f"Discord.py Version: {discord.__version__}")
        self.logger.info(f"--- Tika is now online and ready! ---")