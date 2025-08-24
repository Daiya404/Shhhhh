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
            command_prefix=tuple(["!tika ", "!Tika "]),
            intents=intents,
            help_command=None
        )
        self.logger = logger
        self.command_usage = defaultdict(lambda: defaultdict(list))

    async def setup_hook(self):
        self.logger.info(f"--- Tika is waking up... ---")
        Path("data").mkdir(exist_ok=True)
        cogs_path = Path("cogs")
        cogs_path.mkdir(exist_ok=True)
        Path("utils").mkdir(exist_ok=True)
        
        loaded_cogs = 0
        for cog_file in cogs_path.glob("*.py"):
            if cog_file.name.startswith("_"): continue
            try:
                await self.load_extension(f"cogs.{cog_file.stem}")
                self.logger.info(f"✅ Loaded Cog: {cog_file.name}")
                loaded_cogs += 1
            except Exception as e:
                self.logger.error(f"❌ Failed to load Cog: {cog_file.name}", exc_info=e)
        self.logger.info(f"--- Loaded {loaded_cogs} cog(s) successfully. ---")
        
        try:
            synced = await self.tree.sync()
            self.logger.info(f"🔄 Synced {len(synced)} application command(s).")
        except Exception as e:
            self.logger.error(f"Failed to sync application commands: {e}")

    async def on_message(self, message: discord.Message):
        """This central listener routes every message to the correct feature in order of priority."""
        if message.author.bot:
            return

        # Priority 1: Detention
        detention_cog = self.get_cog("Detention")
        if detention_cog and await detention_cog.is_user_detained(message):
            await detention_cog.handle_detention_message(message)
            return

        # Priority 2: Link Fixer
        link_fixer_cog = self.get_cog("LinkFixer")
        if link_fixer_cog and await link_fixer_cog.check_and_fix_link(message):
            return

        # Priority 3: Word Blocker
        word_blocker_cog = self.get_cog("WordBlocker")
        if word_blocker_cog and await word_blocker_cog.check_and_handle_message(message):
            return

        # Priority 4: Auto Reply (`/nga` feature)
        auto_reply_cog = self.get_cog("AutoReply")
        if auto_reply_cog and await auto_reply_cog.check_for_reply(message):
            return
            
        # Priority 5: Word Game
        word_game_cog = self.get_cog("WordGame")
        if word_game_cog and await word_game_cog.check_word_game_message(message):
            return

        # Get the context ONCE for all remaining checks
        ctx = await self.get_context(message)
        
        # Priority 6: Prefix Commands
        # If the context is valid, it's a command like `!tika eat`. Invoke it.
        if ctx.valid:
            await self.invoke(ctx)
            return # Stop processing, it was a command.
        
        # Priority 7: AI Features (Mentions and Summaries are handled in the cog)
        chatbot_cog = self.get_cog("Chatbot")
        if chatbot_cog and await chatbot_cog.handle_mention(message):
            return # Don't give XP for talking to the bot

        # Final Priority: Leveling System
        # If the message was not a command and not handled by any other system, grant XP.
        leveling_cog = self.get_cog("Leveling")
        if leveling_cog:
            await leveling_cog.process_xp(message)

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