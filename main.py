import discord
from discord.ext import commands
import logging
import os
import asyncio
from pathlib import Path
import signal
import sys

# Configure logging with better formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class OptimizedBot(commands.Bot):
    def __init__(self):
        # Bot configuration with optimized intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        super().__init__(
            command_prefix=['/', '!!'],
            intents=intents,
            help_command=None,  # Disable default help command
            case_insensitive=True,
            strip_after_prefix=True,
            max_messages=1000  # Limit message cache
        )
        
        self.logger = logging.getLogger(__name__)
        self.startup_extensions = [
            'cogs.fun_commands',
            'cogs.moderation', 
            'cogs.word_blocker',
            'cogs.custom_roles',
            'cogs.ngareply',
            'cogs.anime_game'
        ]
        self._shutdown_event = asyncio.Event()

    async def setup_hook(self):
        """Called when the bot is starting up"""
        self.logger.info("Setting up bot...")
        
        # Ensure data directory exists
        Path('data').mkdir(exist_ok=True)
        
        # Load all cogs
        await self.load_cogs()
        
        # Sync slash commands
        try:
            synced = await self.tree.sync()
            self.logger.info(f"Synced {len(synced)} slash command(s)")
        except discord.HTTPException as e:
            self.logger.error(f"Failed to sync commands (HTTP): {e}")
        except Exception as e:
            self.logger.error(f"Failed to sync commands: {e}")

    async def load_cogs(self):
        """Load all cogs with error handling"""
        loaded_count = 0
        for extension in self.startup_extensions:
            try:
                await self.load_extension(extension)
                self.logger.info(f"✅ Loaded {extension}")
                loaded_count += 1
            except commands.ExtensionNotFound:
                self.logger.warning(f"⚠️  Extension {extension} not found")
            except commands.ExtensionFailed as e:
                self.logger.error(f"❌ Failed to load {extension}: {e}")
            except Exception as e:
                self.logger.error(f"❌ Unexpected error loading {extension}: {e}")
        
        self.logger.info(f"Loaded {loaded_count}/{len(self.startup_extensions)} extensions")

    async def on_ready(self):
        """Called when bot is ready"""
        self.logger.info(f'🤖 {self.user} has connected to Discord!')
        self.logger.info(f'📊 Bot is in {len(self.guilds)} guilds')
        
        # Set bot status
        activity = discord.Game(name="with custom roles, nga replies & anime games!")
        await self.change_presence(status=discord.Status.online, activity=activity)

    async def on_message(self, message):
        """Process messages with word blocking"""
        if message.author.bot:
            return
        
        # Process word blocking before other commands
        word_blocker = self.get_cog('WordBlocker')
        if word_blocker:
            try:
                blocked = await word_blocker.check_blocked_words(message)
                if blocked:
                    return  # Message was deleted, don't process further
            except Exception as e:
                self.logger.error(f"Error in word blocker: {e}")
        
        await self.process_commands(message)

    async def on_command_error(self, ctx, error):
        """Global error handler"""
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore unknown commands
        
        if isinstance(error, commands.MissingPermissions):
            await self.safe_send(ctx, "❌ You don't have permission to use this command!", delete_after=5)
            return
        
        if isinstance(error, commands.CommandOnCooldown):
            await self.safe_send(ctx, f"⏰ Command on cooldown. Try again in {error.retry_after:.2f}s", delete_after=5)
            return
        
        if isinstance(error, commands.BotMissingPermissions):
            await self.safe_send(ctx, "❌ I don't have the required permissions to execute this command!", delete_after=5)
            return
        
        if isinstance(error, commands.BadArgument):
            await self.safe_send(ctx, f"❌ Invalid argument provided: {error}", delete_after=5)
            return
        
        self.logger.error(f"Command error in {ctx.command}: {error}")
        await self.safe_send(ctx, "❌ An unexpected error occurred!", delete_after=5)

    async def safe_send(self, ctx, content, **kwargs):
        """Safely send a message with error handling"""
        try:
            await ctx.send(content, **kwargs)
        except discord.Forbidden:
            self.logger.warning(f"No permission to send message in {ctx.guild.name if ctx.guild else 'DM'}")
        except discord.HTTPException as e:
            self.logger.error(f"HTTP error sending message: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error sending message: {e}")

    async def on_guild_join(self, guild):
        """Log when bot joins a guild"""
        self.logger.info(f"➕ Joined guild: {guild.name} (ID: {guild.id})")

    async def on_guild_remove(self, guild):
        """Log when bot leaves a guild"""
        self.logger.info(f"➖ Left guild: {guild.name} (ID: {guild.id})")

    async def close(self):
        """Cleanup when bot is shutting down"""
        self.logger.info("🔄 Shutting down bot...")
        self._shutdown_event.set()
        await super().close()
        self.logger.info("✅ Bot shutdown complete")

def signal_handler(bot):
    """Handle shutdown signals"""
    def handler(signum, frame):
        logging.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(bot.close())
    return handler

async def main():
    """Main function to run the bot"""
    bot = OptimizedBot()
    
    # Set up signal handlers for graceful shutdown
    if sys.platform != 'win32':
        signal.signal(signal.SIGTERM, signal_handler(bot))
        signal.signal(signal.SIGINT, signal_handler(bot))
    
    # Get token from environment variable or file
    token = os.getenv("BOT_TOKEN", "").strip()

    if not token:
        try:
            token_file = Path('token.txt')
            if token_file.exists():
                with open(token_file, 'r', encoding='utf-8') as f:
                    token = f.read().strip()
            else:
                logging.error("❌ No bot token found! Set BOT_TOKEN environment variable or create token.txt")
                exit(1)  # Exit if token is not found
        except Exception as e:
            logging.error(f"❌ Error reading token file: {e}")
            exit(1)

    logging.info("✅ Bot token loaded successfully!")
    
    if not token:
        logging.error("❌ Bot token is empty!")
        return
    
    try:
        async with bot:
            await bot.start(token)
    except KeyboardInterrupt:
        logging.info("🛑 Bot stopped by user")
    except discord.LoginFailure:
        logging.error("❌ Invalid bot token!")
    except discord.HTTPException as e:
        logging.error(f"❌ HTTP error: {e}")
    except Exception as e:
        logging.error(f"❌ Bot crashed: {e}")
    finally:
        if not bot.is_closed():
            await bot.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Program interrupted")
    except Exception as e:
        logging.error(f"❌ Fatal error: {e}")
        sys.exit(1)
