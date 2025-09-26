# core/bot.py
import discord
from discord.ext import commands
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from services.data_manager import DataManager
from services.admin_manager import AdminManager
from services.feature_manager import FeatureManager
from core.personality import PersonalityManager

logger = logging.getLogger(__name__)

class TikaBot(commands.Bot):
    def __init__(self, secrets: Dict[str, Any]):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        
        super().__init__(
            command_prefix=self._get_prefix,
            intents=intents,
            help_command=None,  # We'll implement our own
            case_insensitive=True
        )
        
        # Store secrets and initialize services
        self.secrets = secrets
        self.data_manager = DataManager()
        self.admin_manager = AdminManager(self)
        self.feature_manager = FeatureManager(self)
        self.personality = PersonalityManager()
        
        # Bot state
        self._ready = False

    async def _get_prefix(self, bot, message):
        """Dynamic prefix getter - can be customized per guild."""
        # Default prefix, but could be made configurable per guild
        return "!"

    async def setup_hook(self):
        """Called when the bot is starting up."""
        try:
            # Initialize services
            await self.data_manager.init_path()
            await self.admin_manager.load_cache()
            await self.feature_manager.load_cache()
            
            # Load cogs
            await self._load_cogs()
            
            # Sync app commands globally (or per guild for development)
            if self.secrets.get("debug_mode", "false").lower() == "true":
                # Sync to specific guild for faster updates during development
                guild_id = self.secrets.get("debug_guild_id")
                if guild_id:
                    guild = discord.Object(id=int(guild_id))
                    self.tree.copy_global_to(guild=guild)
                    await self.tree.sync(guild=guild)
                    logger.info(f"Synced commands to debug guild {guild_id}")
            else:
                await self.tree.sync()
                logger.info("Synced commands globally")
            
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}")
            raise

    async def _load_cogs(self):
        """Load all cogs from the cogs directory."""
        cogs_dir = Path("cogs")
        if not cogs_dir.exists():
            logger.warning("Cogs directory not found")
            return
        
        loaded = 0
        failed = 0
        
        for cog_file in cogs_dir.glob("*.py"):
            if cog_file.name.startswith("_"):
                continue
                
            cog_name = f"cogs.{cog_file.stem}"
            try:
                await self.load_extension(cog_name)
                logger.info(f"Loaded cog: {cog_name}")
                loaded += 1
            except Exception as e:
                logger.error(f"Failed to load cog {cog_name}: {e}")
                failed += 1
        
        logger.info(f"Cog loading complete: {loaded} loaded, {failed} failed")

    async def on_ready(self):
        """Called when the bot is fully ready."""
        if not self._ready:
            self._ready = True
            logger.info(f"Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
            logger.info(f"Connected to {len(self.guilds)} guilds")
            
            # Set status
            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name="your commands"
            )
            await self.change_presence(activity=activity, status=discord.Status.online)

    async def on_guild_join(self, guild):
        """Called when the bot joins a new guild."""
        logger.info(f"Joined guild: {guild.name} (ID: {guild.id})")

    async def on_guild_remove(self, guild):
        """Called when the bot is removed from a guild."""
        logger.info(f"Removed from guild: {guild.name} (ID: {guild.id})")

    async def on_command_error(self, ctx, error):
        """Global command error handler."""
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore unknown commands
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("I don't have the required permissions to execute this command.")
        else:
            logger.error(f"Unhandled command error: {error}")
            await ctx.send("An error occurred while processing your command.")

    async def close(self):
        """Clean up when the bot shuts down."""
        logger.info("Bot is shutting down...")
        await super().close()