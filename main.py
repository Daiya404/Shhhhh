# main.py
import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

class TikaBot(commands.Bot):
    def __init__(self):
        # Define intents for the bot
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        # Initialize the bot with a command prefix and intents
        # The prefix is only for the !Tika nuke command now
        super().__init__(command_prefix='!Tika ', intents=intents)

    async def setup_hook(self):
        # Create data directory if it doesn't exist
        if not os.path.exists('data'):
            os.makedirs('data')

        # Load all cogs from the 'cogs' directory
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f'Successfully loaded cog: {filename}')
                except Exception as e:
                    print(f'Failed to load cog {filename}: {e}')

    async def on_ready(self):
        print(f'Logged in as {self.user.name} ({self.user.id})')
        print('------')
        
        # --- THIS IS THE CRITICAL ADDITION ---
        # Sync the command tree with Discord to register/update all slash commands.
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")
        # ------------------------------------

        # Set bot's presence
        await self.change_presence(activity=discord.Game(name="with your feelings"))


async def main():
    bot = TikaBot()
    await bot.start(TOKEN)

if __name__ == '__main__':
    asyncio.run(main())