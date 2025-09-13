# core/bot.py
import discord
from discord.ext import commands
import logging
from collections import defaultdict
import aiohttp
import asyncio
import random

from config.settings import Settings
from services.data_manager import DataManager
from services.gemini_service import GeminiService
from services.knowledge_service import KnowledgeService
from services.web_search_service import WebSearchService

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
        self.http_session = aiohttp.ClientSession()
        self.web_search_service = WebSearchService(self.http_session)
        self.gemini_service = GeminiService(
            api_key=self.settings.GEMINI_API_KEY, 
            web_search_service=self.web_search_service
        )
        self.knowledge_service = KnowledgeService(self.data_manager, self.gemini_service)
        
        # Bot state tracking
        self.command_usage = defaultdict(lambda: defaultdict(list))
        self.start_time = None
        self.last_message_times = {}  # Track when users last messaged
        self.typing_delays = {}  # Add realistic typing delays

    async def close(self):
        await super().close()
        await self.http_session.close()

    async def setup_hook(self):
        await self.knowledge_service.on_ready()
        self.logger.info("--- Tika is waking up... ---")
        
        # Ensure directories exist
        self.settings.DATA_DIR.mkdir(exist_ok=True)
        self.settings.LOGS_DIR.mkdir(exist_ok=True)
        
        # Load cogs with better error handling
        loaded_cogs = 0
        failed_cogs = []
        
        for folder in self.settings.COGS_DIR.iterdir():
            if folder.is_dir() and not folder.name.startswith('_'):
                for file in folder.glob("*.py"):
                    if not file.name.startswith("_"):
                        try:
                            extension = f"cogs.{folder.name}.{file.stem}"
                            await self.load_extension(extension)
                            self.logger.info(f"✅ Loaded Cog: {extension}")
                            loaded_cogs += 1
                        except Exception as e:
                            failed_cogs.append((extension, str(e)))
                            self.logger.error(f"❌ Failed to load Cog: {extension}", exc_info=e)
        
        self.logger.info(f"--- Loaded {loaded_cogs} cog(s) successfully. ---")
        if failed_cogs:
            self.logger.warning(f"Failed to load {len(failed_cogs)} cogs: {[cog[0] for cog in failed_cogs]}")
        
        # Sync commands
        try:
            synced = await self.tree.sync()
            self.logger.info(f"🔄 Synced {len(synced)} application command(s) globally.")
        except Exception as e:
            self.logger.error(f"Failed to sync commands: {e}")

    def _calculate_realistic_typing_time(self, response_length: int) -> float:
        """Calculate realistic typing time based on response length."""
        base_time = 0.5  # Minimum typing time
        typing_speed = 0.05  # Seconds per character (adjustable)
        thinking_time = min(2.0, len(response_length) / 50)  # Brief thinking time
        
        return base_time + (response_length * typing_speed) + thinking_time

    async def _send_with_realistic_timing(self, messageable, content: str, mention_author: bool = False, reference_message=None):
        """Send message with realistic typing delays to make Tika feel more human."""
        typing_time = self._calculate_realistic_typing_time(len(content))
        
        async with messageable.typing():
            await asyncio.sleep(min(typing_time, 5.0))  # Cap at 5 seconds max
            
            if reference_message:
                return await reference_message.reply(content, mention_author=mention_author)
            else:
                return await messageable.send(content)

    async def on_message(self, message: discord.Message):
        # Ignore bot messages and DMs
        if message.author.bot or not message.guild:
            return
            
        feature_manager = self.get_cog("FeatureManager")
        if not feature_manager:
            return

        # Track message timing for better interaction
        self.last_message_times[message.author.id] = discord.utils.utcnow()

        # Check for direct mentions
        is_mention = self.user.mentioned_in(message) and not message.mention_everyone
        is_reply = (message.reference and 
                   isinstance(message.reference.resolved, discord.Message) and 
                   message.reference.resolved.author == self.user)

        # Handle AI interactions
        if is_mention:
            content = message.clean_content.replace(f"@{self.user.name}", "").strip()
            
            # Special command: summarize
            if content.lower().startswith("summarize"):
                await self._handle_summarize_request(message)
                return
                
            # Regular AI conversation
            await self._handle_ai_conversation(message, is_mention=True)
            return

        if is_reply and feature_manager.is_feature_enabled(message.guild.id, "ai_chat"):
            await self._handle_ai_conversation(message, is_mention=False)
            return

        # Handle other features (existing code)
        if feature_manager.is_feature_enabled(message.guild.id, "detention_system"):
            if (detention_cog := self.get_cog("Detention")) and await detention_cog.is_user_detained(message):
                await detention_cog.handle_detention_message(message)
                return

        if feature_manager.is_feature_enabled(message.guild.id, "word_blocker"):
            if (word_blocker_cog := self.get_cog("WordBlocker")) and await word_blocker_cog.check_and_handle_message(message):
                return

        if feature_manager.is_feature_enabled(message.guild.id, "link_fixer"):
            if (link_fixer_cog := self.get_cog("LinkFixer")):
                await link_fixer_cog.check_and_fix_link(message)

        if feature_manager.is_feature_enabled(message.guild.id, "auto_reply"):
            if (auto_reply_cog := self.get_cog("AutoReply")) and await auto_reply_cog.check_for_reply(message):
                return

        if feature_manager.is_feature_enabled(message.guild.id, "word_game"):
            if (word_game_cog := self.get_cog("WordGame")) and await word_game_cog.check_word_game_message(message):
                return
        
        # Process commands
        ctx = await self.get_context(message)
        if ctx.valid:
            await self.invoke(ctx)
            
    async def on_ready(self):
        if not self.start_time:
            self.start_time = discord.utils.utcnow()
            
        # Set a more personality-appropriate status
        status_messages = [
            "Doing things. Perfectly, of course.",
            "Organizing my thoughts. Again.",
            "Reading. Don't interrupt.",
            "Managing chaos, as usual.",
            "Being helpful. You're welcome."
        ]
        
        activity = discord.Game(name=random.choice(status_messages))
        await self.change_presence(status=discord.Status.online, activity=activity)
        
        self.logger.info("---")
        self.logger.info(f"Logged in as: {self.user} (ID: {self.user.id})")
        self.logger.info(f"Serving {len(self.guilds)} server(s).")
        self.logger.info(f"Discord.py Version: {discord.__version__}")
        self.logger.info(f"--- Tika is now online and ready! ---")
        
    async def _handle_summarize_request(self, message: discord.Message):
        """Handle conversation summarization with personality."""
        feature_manager = self.get_cog("FeatureManager")
        if feature_manager and not feature_manager.is_feature_enabled(message.guild.id, "ai_summarize"):
            responses = [
                "The summarize feature is disabled here. *shrugs* Not my problem.",
                "I'm not allowed to summarize on this server. Take it up with the admins.",
                "Summarizing is turned off here. Sorry, I guess."
            ]
            return await self._send_with_realistic_timing(
                message.channel, random.choice(responses), 
                reference_message=message, mention_author=False
            )
            
        if not self.gemini_service or not self.gemini_service.is_ready():
            error_responses = [
                "My brain is offline. Can't summarize anything right now.",
                "Nothing's working up here. Try again later.",
                "I literally can't think right now. Sorry."
            ]
            return await self._send_with_realistic_timing(
                message.channel, random.choice(error_responses),
                reference_message=message, mention_author=False
            )

        try:
            # Get recent message history
            history = []
            async for msg in message.channel.history(limit=50, before=message):
                if not msg.author.bot and msg.clean_content.strip():
                    history.append(f"{msg.author.display_name}: {msg.clean_content}")
                    
            if not history:
                no_history_responses = [
                    "There's literally nothing here to summarize. *looks around confused*",
                    "What conversation? I don't see anything worth summarizing.",
                    "You want me to summarize... nothing? Okay then."
                ]
                return await self._send_with_realistic_timing(
                    message.channel, random.choice(no_history_responses),
                    reference_message=message, mention_author=False
                )

            history.reverse()  # Chronological order
            summary = await self.gemini_service.summarize_conversation(history)
            
            await self._send_with_realistic_timing(
                message.channel, summary, 
                reference_message=message, mention_author=False
            )
            
        except Exception as e:
            self.logger.error(f"Summarization failed: {e}")
            error_responses = [
                "Something went wrong while I was trying to make sense of that mess.",
                "I couldn't summarize that for some reason.",
                "My brain just... noped out. Can't summarize that.",
                "Yeah, that didn't work. Try again maybe?"
            ]
            await self._send_with_realistic_timing(
                message.channel, random.choice(error_responses),
                reference_message=message, mention_author=False
            )

    async def _handle_ai_conversation(self, message: discord.Message, is_mention: bool):
        """Handle AI conversation with improved personality and context."""
        chat_cog = self.get_cog("AIChat")
        if not chat_cog or not chat_cog.gemini_service.is_ready():
            return

        user_id = message.author.id
        history = chat_cog.conversation_history[user_id]
        
        # Process the user's message
        if is_mention:
            user_message_content = message.clean_content.replace(f"@{self.user.name}", "").strip()
            # Clear history for new mentions to start fresh
            history.clear()
        else:
            user_message_content = message.clean_content

        # Add user message to history
        history.append({"role": "user", "parts": [user_message_content]})
        
        # Trim history to prevent context bloat
        if len(history) > 20:
            chat_cog.conversation_history[user_id] = history[-20:]
            history = chat_cog.conversation_history[user_id]

        try:
            # Generate response with user context
            response_text = await chat_cog.gemini_service.generate_chat_response(
                user_message=user_message_content, 
                conversation_history=history,
                user_id=user_id  # Pass user ID for relationship tracking
            )
            
            # Add response to history
            history.append({"role": "model", "parts": [response_text]})
            
            # Send with realistic timing
            await self._send_with_realistic_timing(
                message.channel, response_text,
                reference_message=message, mention_author=False
            )
            
        except Exception as e:
            self.logger.error(f"AI conversation failed: {e}")
            error_responses = [
                "*stares blankly* Sorry, what were we talking about?",
                "My brain just froze. Give me a second... *confused*",
                "I completely lost my train of thought. What was the question?",
                "*looks flustered* Um... can you repeat that? I wasn't paying attention."
            ]
            
            await self._send_with_realistic_timing(
                message.channel, random.choice(error_responses),
                reference_message=message, mention_author=False
            )