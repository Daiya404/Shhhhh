# core/bot.py
import discord
from discord.ext import commands
import os
import logging

from services.data_manager import DataManager
from services.admin_manager import AdminManager
from services.feature_manager import FeatureManager

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TikaBot(commands.Bot):
    def __init__(self):
        # Define intents: what events the bot listens to
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        
        super().__init__(command_prefix="!", intents=intents)
        
        # Initialize services and attach them to the bot instance
        self.data_manager = DataManager()
        self.admin_manager = AdminManager(self)
        self.feature_manager = FeatureManager(self)

    async def setup_hook(self):
        """This is called once the bot is ready, before it connects to Discord."""
        # Load services that require async setup
        await self.data_manager.init_path()
        await self.admin_manager.load_cache()
        await self.feature_manager.load_cache()

        # Load all command cogs
        print("Loading cogs...")
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and not filename.startswith('_'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f"  > Loaded {filename}")
                except Exception as e:
                    print(f"  > Failed to load {filename}: {e}")
        print("Cogs loaded.")

    async def on_ready(self):
        """Event that fires when the bot is fully connected."""
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')