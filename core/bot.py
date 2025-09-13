# core/bot.py
import discord
from discord.ext import commands
import logging
from collections import defaultdict
import aiohttp

from config.settings import Settings
from services.data_manager import DataManager
from services.gemini_service import GeminiService
from services.knowledge_service import KnowledgeService

class TikaBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True
        super().__init__(command_prefix=settings.COMMAND_PREFIX, intents=intents, help_command=None)
        
        self.settings = settings
        self.logger = logging.getLogger('discord')
        
        # Initialize all core services
        self.data_manager = DataManager(base_path=self.settings.DATA_DIR)
        self.http_session = aiohttp.ClientSession()
        self.gemini_service = GeminiService(api_key=self.settings.GEMINI_API_KEY)
        self.knowledge_service = KnowledgeService(self.data_manager, self.gemini_service)
        
        self.command_usage = defaultdict(lambda: defaultdict(list))

    async def close(self):
        """Cleanly closes the bot and its services upon shutdown."""
        await super().close()
        await self.http_session.close()

    async def setup_hook(self):
        """Initializes the bot, loads cogs, and syncs commands."""
        # Load persistent knowledge before loading cogs that might use it.
        await self.knowledge_service.on_ready()
        
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
        """The definitive Traffic Cop: Handles all message-based interactions in order of priority."""
        if message.author.bot or not message.guild:
            return

        feature_manager = self.get_cog("FeatureManager")
        if not feature_manager: return # A critical cog is missing, do nothing.

        # --- AI & SPECIAL INTERACTIONS (HIGHEST PRIORITY) ---

        # Priority 1: Bot Mention Utilities (@Tika summarize)
        if self.user.mentioned_in(message) and not message.mention_everyone:
            content = message.clean_content.replace(f"@{self.user.name}", "").strip()
            if content.lower().startswith("summarize"):
                await self.handle_summarize_request(message)
                return

        # Priority 2: Reply-to-Continue AI Conversation
        if message.reference and isinstance(message.reference.resolved, discord.Message) and message.reference.resolved.author == self.user:
            if feature_manager.is_feature_enabled(message.guild.id, "ai_chat"):
                await self.handle_chat_reply(message)
                return

        # --- MODERATION & ENFORCEMENT ---

        # Priority 3: Detention
        if feature_manager.is_feature_enabled(message.guild.id, "detention_system"):
            detention_cog = self.get_cog("Detention")
            if detention_cog and await detention_cog.is_user_detained(message):
                await detention_cog.handle_detention_message(message)
                return

        # Priority 4: Word Blocker
        if feature_manager.is_feature_enabled(message.guild.id, "word_blocker"):
            word_blocker_cog = self.get_cog("WordBlocker")
            if word_blocker_cog and await word_blocker_cog.check_and_handle_message(message):
                return

        # --- CONTENT AUGMENTATION & RESPONSE ---
        
        # Priority 5: Link Fixer (Does not stop processing, so no `return`)
        if feature_manager.is_feature_enabled(message.guild.id, "link_fixer"):
            link_fixer_cog = self.get_cog("LinkFixer")
            if link_fixer_cog:
                await link_fixer_cog.check_and_fix_link(message)

        # Priority 6: Auto Reply
        if feature_manager.is_feature_enabled(message.guild.id, "auto_reply"):
            auto_reply_cog = self.get_cog("AutoReply")
            if auto_reply_cog and await auto_reply_cog.check_for_reply(message):
                return

        # Priority 7: Word Game
        if feature_manager.is_feature_enabled(message.guild.id, "word_game"):
            word_game_cog = self.get_cog("WordGame")
            if word_game_cog and await word_game_cog.check_word_game_message(message):
                return
        
        # --- FALLBACK: PREFIX COMMANDS ---
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
        
    # --- Helper Methods for on_message ---
    async def handle_summarize_request(self, message: discord.Message):
        feature_manager = self.get_cog("FeatureManager")
        if feature_manager and not feature_manager.is_feature_enabled(message.guild.id, "ai_summarize"):
            return await message.reply("The Summarize feature is disabled on this server.", mention_author=False)
        
        if not self.gemini_service or not self.gemini_service.is_ready():
            return await message.reply("My AI brain is offline. Can't summarize.", mention_author=False)

        async with message.channel.typing():
            try:
                history = [f"{msg.author.display_name}: {msg.clean_content}" async for msg in message.channel.history(limit=50, before=message) if not msg.author.bot]
                if not history:
                    return await message.reply("There's nothing for me to summarize. This conversation is boring.", mention_author=False)
                
                history.reverse()
                summary = await self.gemini_service.summarize_conversation(history)
                await message.reply(summary, mention_author=False)
            except Exception as e:
                self.logger.error(f"Summarization failed: {e}")
                await message.reply("I couldn't summarize that for some reason. Probably your fault.", mention_author=False)

    async def handle_chat_reply(self, message: discord.Message):
        chat_cog = self.get_cog("AIChat")
        if not chat_cog or not chat_cog.gemini_service.is_ready(): return

        async with message.channel.typing():
            user_id = message.author.id
            history = chat_cog.conversation_history[user_id]
            user_message_content = message.clean_content
            
            history.append({"role": "user", "parts": [user_message_content]})
            if len(history) > 20: # Keep history trimmed
                chat_cog.conversation_history[user_id] = history[-20:]
                history = chat_cog.conversation_history[user_id]
            
            response_text = await chat_cog.gemini_service.generate_chat_response(
                user_message=user_message_content,
                conversation_history=history
            )
            history.append({"role": "model", "parts": [response_text]})
            
            await message.reply(response_text, mention_author=False)