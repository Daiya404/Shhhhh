# core/bot.py
from typing import Optional
import discord
from discord.ext import commands
from discord.errors import ConnectionClosed, GatewayNotFound, HTTPException
import logging
from collections import defaultdict
import aiohttp
import asyncio
import random
import traceback
import time

from polars import datetime

from config.settings import Settings
from services.github_backup_service import GitHubBackupService
from services.data_manager import DataManager
from services.resource_monitor import ResourceMonitor

class TikaBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True
        
        super().__init__(command_prefix=settings.COMMAND_PREFIX, intents=intents, help_command=None)
        
        self.settings = settings
        self.logger = logging.getLogger('discord')
        
        # Services
        self.data_manager = DataManager(base_path=self.settings.DATA_DIR)
        self.http_session = None  # Initialize in setup_hook
        self.backup_service = None
        self.resource_monitor = None
        
        # Bot state tracking
        self.command_usage = defaultdict(lambda: defaultdict(list))
        self.start_time: Optional[datetime] = None
        self.last_message_times = {}  # Track when users last messaged
        self.typing_delays = {}  # Add realistic typing delays
        
        # Network resilience settings
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 30  # seconds
        self.network_error_count = 0
        self.last_network_error = 0
        
        # Error tracking
        self.error_count = defaultdict(int)
        self.last_errors = {}

    async def setup_hook(self):
        """Initialize services and load cogs with enhanced error handling."""
        try:
            self.logger.info("--- Tika is waking up... ---")
            
            # Initialize HTTP session with proper error handling
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=60,
                enable_cleanup_closed=True
            )
            
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self.http_session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                raise_for_status=False
            )
            
            # Initialize services with error handling
            await self._initialize_services()
            
            # Ensure directories exist
            self.settings.DATA_DIR.mkdir(exist_ok=True)
            self.settings.LOGS_DIR.mkdir(exist_ok=True)
            
            # Load cogs with better error handling
            await self._load_cogs_safely()
            
            # Sync commands with retry logic
            await self._sync_commands_with_retry()
            
        except Exception as e:
            self.logger.critical(f"Critical error in setup_hook: {e}", exc_info=True)
            raise

    async def _initialize_services(self):
        """Initialize all bot services with error handling."""
        try:
            # All AI and WebSearch services have been removed from here
            
            # Initialize backup service if configured
            if self.settings.GITHUB_TOKEN and self.settings.GITHUB_REPO:
                try:
                    self.backup_service = GitHubBackupService(self.settings)
                    self.logger.info("Backup service initialized")
                except Exception as e:
                    self.logger.warning(f"Backup service failed to initialize: {e}")
                    
            # Initialize resource monitor
            try:
                self.resource_monitor = ResourceMonitor()
                self.logger.info("Resource monitor initialized")
            except Exception as e:
                self.logger.warning(f"Resource monitor failed to initialize: {e}")
                
        except Exception as e:
            self.logger.error(f"Error initializing services: {e}", exc_info=True)

    async def _load_cogs_safely(self):
        """Load cogs with comprehensive error handling."""
        loaded_cogs = 0
        failed_cogs = []
        
        try:
            for folder in self.settings.COGS_DIR.iterdir():
                if folder.is_dir() and not folder.name.startswith('_'):
                    # --- MODIFICATION: Skip the 'ai' directory ---
                    if folder.name == 'ai':
                        continue
                    for file in folder.glob("*.py"):
                        if not file.name.startswith("_"):
                            extension = f"cogs.{folder.name}.{file.stem}"
                            try:
                                await self.load_extension(extension)
                                self.logger.info(f"✅ Loaded Cog: {extension}")
                                loaded_cogs += 1
                            except Exception as e:
                                failed_cogs.append((extension, str(e)))
                                self.logger.error(f"❌ Failed to load Cog: {extension}", exc_info=True)
        except Exception as e:
            self.logger.error(f"Error during cog loading process: {e}", exc_info=True)
        
        self.logger.info(f"--- Loaded {loaded_cogs} cog(s) successfully. ---")
        if failed_cogs:
            self.logger.warning(f"Failed to load {len(failed_cogs)} cogs:")
            for cog_name, error in failed_cogs:
                self.logger.warning(f"  {cog_name}: {error}")

    async def _sync_commands_with_retry(self):
        """Sync application commands with retry logic."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                synced = await self.tree.sync()
                self.logger.info(f"Synced {len(synced)} application command(s) globally.")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    self.logger.warning(f"Command sync failed (attempt {attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    self.logger.error(f"Failed to sync commands after {max_retries} attempts: {e}")

    async def close(self):
        """Enhanced cleanup on bot shutdown."""
        self.logger.info("Shutting down Tika Bot...")
        
        try:
            # Save any pending data
            if hasattr(self, 'data_manager') and self.data_manager:
                try:
                    # Save error statistics
                    error_data = {
                        "error_counts": dict(self.error_count),
                        "network_errors": self.network_error_count,
                        "last_shutdown": time.time()
                    }
                    await self.data_manager.save_data("bot_errors", error_data)
                except Exception as e:
                    self.logger.error(f"Error saving bot data: {e}")
                
            # Close HTTP session safely
            if hasattr(self, 'http_session') and self.http_session and not self.http_session.closed:
                await self.http_session.close()
                await asyncio.sleep(0.1)  # Give time for cleanup
                
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            
        await super().close()

    def _calculate_realistic_typing_time(self, response_length: int) -> float:
        """Calculate realistic typing time based on response length."""
        base_time = 0.5
        typing_speed = 0.05
        thinking_time = min(2.0, response_length * 0.02)
        return base_time + (response_length * typing_speed) + thinking_time

    async def _send_with_realistic_timing(self, messageable, content: str, mention_author: bool = False, reference_message=None):
        """Send message with realistic typing delays to make Tika feel more human."""
        try:
            typing_time = self._calculate_realistic_typing_time(len(content))
            
            async with messageable.typing():
                await asyncio.sleep(min(typing_time, 5.0))  # Cap at 5 seconds max
                
                if reference_message:
                    return await reference_message.reply(content, mention_author=mention_author)
                else:
                    return await messageable.send(content)
                    
        except discord.Forbidden:
            self.logger.warning(f"Missing permissions to send message in {messageable}")
        except discord.HTTPException as e:
            self.logger.error(f"HTTP error sending message: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error sending message: {e}")

    async def on_error(self, event, *args, **kwargs):
        """Enhanced error handling for various Discord events."""
        error_key = f"{event}:{type(args[0]).__name__ if args else 'unknown'}"
        self.error_count[error_key] += 1
        
        # Rate limit error logging
        current_time = time.time()
        if error_key in self.last_errors and current_time - self.last_errors[error_key] < 60:
            return  # Don't spam logs with the same error
            
        self.last_errors[error_key] = current_time
        
        self.logger.error(f'Error in {event} (occurrence #{self.error_count[error_key]}):')
        self.logger.error(traceback.format_exc())
        
        # Handle specific error types
        if event == 'on_message' and args:
            message = args[0]
            if hasattr(message, 'author') and hasattr(message, 'guild') and hasattr(message, 'channel'):
                self.logger.error(f'Error processing message from {message.author} in {message.guild}#{message.channel}')

    async def on_disconnect(self):
        """Handle disconnection events gracefully."""
        self.logger.warning("Bot disconnected from Discord. Will attempt to reconnect...")
        self.network_error_count += 1
        self.last_network_error = time.time()
        
        # If too many network errors, implement backoff
        if self.network_error_count > 3:
            self.logger.warning(f"Multiple network issues detected ({self.network_error_count}). "
                              "This might be a temporary connectivity problem.")

    async def on_resumed(self):
        """Handle successful reconnection."""
        self.logger.info("Successfully reconnected to Discord!")
        self.network_error_count = max(0, self.network_error_count - 1)  # Slowly reduce error count

    async def on_message(self, message: discord.Message):
        """Enhanced message handling with comprehensive error recovery."""
        try:
            # Ignore bot messages and DMs
            if message.author.bot or not message.guild:
                return
                
            feature_manager = self.get_cog("FeatureManager")
            if not feature_manager:
                # Process commands even if feature manager is unavailable
                ctx = await self.get_context(message)
                if ctx.valid:
                    await self.invoke(ctx)
                return

            # Track message timing for better interaction
            self.last_message_times[message.author.id] = discord.utils.utcnow()

            # All AI-related checks (mentions, replies) have been removed from here.

            # Handle other features with error isolation
            await self._process_message_features(message, feature_manager)
            
            # Process commands
            ctx = await self.get_context(message)
            if ctx.valid:
                await self.invoke(ctx)
                
        except Exception as e:
            self.logger.error(f"Error in on_message: {e}", exc_info=True)

    async def _process_message_features(self, message, feature_manager):
        """Process message through various features with error isolation."""
        features_to_check = [
            ("detention_system", "Detention", "is_user_detained", "handle_detention_message"),
            ("word_blocker", "WordBlocker", "check_and_handle_message", None),
            ("link_fixer", "LinkFixer", "check_and_fix_link", None),
            ("auto_reply", "AutoReply", "check_for_reply", None),
            ("word_game", "WordGame", "check_word_game_message", None),
        ]
        
        for feature_name, cog_name, check_method, handle_method in features_to_check:
            if not feature_manager.is_feature_enabled(message.guild.id, feature_name):
                continue
                
            try:
                cog = self.get_cog(cog_name)
                if not cog:
                    continue
                    
                # Handle detention system specially
                if feature_name == "detention_system":
                    if hasattr(cog, check_method):
                        if await getattr(cog, check_method)(message):
                            if handle_method and hasattr(cog, handle_method):
                                await getattr(cog, handle_method)(message)
                            return  # Stop processing other features
                else:
                    # Handle other features
                    if hasattr(cog, check_method):
                        result = await getattr(cog, check_method)(message)
                        if result:
                            return  # Stop processing if feature handled the message
                            
            except Exception as e:
                self.logger.error(f"Error in {feature_name} feature: {e}")
                continue  # Continue with other features

    async def on_ready(self):
        """Enhanced on_ready with better status management."""
        if not self.start_time:
            self.start_time = discord.utils.utcnow()
            
        # Reset network error count on successful startup
        self.network_error_count = 0
        
        # Set a more personality-appropriate status
        status_messages = [
            "Doing things. Perfectly, of course.",
            "Organizing my thoughts. Again.",
            "Reading. Don't interrupt.",
            "Managing chaos, as usual.",
            "Being helpful. You're welcome.",
            "Judging your life choices.",
            "Contemplating existence.",
            "Fixing everyone's problems."
        ]
        
        try:
            activity = discord.Game(name=random.choice(status_messages))
            await self.change_presence(status=discord.Status.online, activity=activity)
        except Exception as e:
            self.logger.warning(f"Could not set status: {e}")
            
        guild_count = len(self.guilds)
        user_count = sum(guild.member_count or 0 for guild in self.guilds)
        
        self.logger.info("---")
        self.logger.info(f"Logged in as: {self.user} (ID: {self.user.id})")
        self.logger.info(f"Serving {guild_count} server(s) with ~{user_count:,} users.")
        self.logger.info(f"Discord.py Version: {discord.__version__}")
        self.logger.info(f"--- Tika is now online and ready! ---")
        
    # The AI-specific helper methods (_handle_summarize_request, _handle_ai_conversation) have been deleted.