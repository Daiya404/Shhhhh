# core/bot.py
from typing import Optional
import discord
from discord.ext import commands
import logging
from collections import defaultdict
import aiohttp
import asyncio
import random
from datetime import datetime

from config.settings import Settings
from services.github_backup_service import GitHubBackupService
from services.data_manager import DataManager
from services.gemini_service import GeminiService
from services.knowledge_service import KnowledgeService
from services.relationship_manager import RelationshipManager
from services.web_search_service import WebSearchService
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
        self.http_session = aiohttp.ClientSession()
        self.web_search_service = WebSearchService(self.http_session)
        self.relationship_manager = RelationshipManager(self.data_manager)
        self.gemini_service = GeminiService(
            api_key=self.settings.GEMINI_API_KEY, 
            web_search_service=self.web_search_service,
            relationship_manager=self.relationship_manager
        )
        self.knowledge_service = KnowledgeService(self.data_manager, self.gemini_service)

        self.backup_service = GitHubBackupService(self.settings)
        self.resource_monitor = ResourceMonitor()
        
        # Bot state tracking
        self.command_usage = defaultdict(lambda: defaultdict(list))
        self.start_time: Optional[datetime] = None
        self.last_message_times = {}  # Track when users last messaged
        self.typing_delays = {}  # Add realistic typing delays
        
        # Message handling state
        self.processing_messages = set()  # Prevent duplicate processing

    async def close(self):
        await super().close()
        await self.http_session.close()

    async def setup_hook(self):
        await self.knowledge_service.on_ready()
        await self.relationship_manager.on_ready()
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
                            self.logger.info(f"Loaded Cog: {extension}")
                            loaded_cogs += 1
                        except Exception as e:
                            failed_cogs.append((extension, str(e)))
                            self.logger.error(f"Failed to load Cog: {extension}", exc_info=e)
        
        self.logger.info(f"--- Loaded {loaded_cogs} cog(s) successfully. ---")
        if failed_cogs:
            self.logger.warning(f"Failed to load {len(failed_cogs)} cogs: {[cog[0] for cog in failed_cogs]}")
        
        # Sync commands
        try:
            synced = await self.tree.sync()
            self.logger.info(f"Synced {len(synced)} application command(s) globally.")
        except Exception as e:
            self.logger.error(f"Failed to sync commands: {e}")

    def _calculate_realistic_typing_time(self, response_length: int) -> float:
        """Calculate realistic typing time based on response length."""
        base_time = 0.5
        typing_speed = 0.04  # Slightly faster than before
        thinking_time = min(1.5, response_length * 0.015)
        return base_time + (response_length * typing_speed) + thinking_time

    async def _send_with_realistic_timing(self, messageable, content: str, mention_author: bool = False, reference_message=None):
        """Send message with realistic typing delays and proper error handling."""
        if not content or len(content.strip()) == 0:
            self.logger.warning("Attempted to send empty message")
            return None
            
        # Ensure message fits Discord's limits
        if len(content) > 2000:
            self.logger.warning(f"Message too long ({len(content)} chars), truncating")
            content = content[:1950] + "\n\n...and I'm cutting myself off there."
        
        typing_time = self._calculate_realistic_typing_time(len(content))
        
        try:
            async with messageable.typing():
                await asyncio.sleep(min(typing_time, 4.0))  # Cap at 4 seconds max
                
                if reference_message:
                    return await reference_message.reply(content, mention_author=mention_author)
                else:
                    return await messageable.send(content)
                    
        except discord.HTTPException as e:
            if e.code == 50035:  # Invalid form body (message too long)
                self.logger.error(f"Discord message too long error: {len(content)} characters")
                truncated = content[:1500] + "\n\n...I have to cut this short. Discord won't let me finish."
                try:
                    if reference_message:
                        return await reference_message.reply(truncated, mention_author=mention_author)
                    else:
                        return await messageable.send(truncated)
                except Exception as retry_error:
                    self.logger.error(f"Failed to send even truncated message: {retry_error}")
                    return None
            else:
                self.logger.error(f"Discord HTTP error: {e}")
                return None
        except discord.Forbidden:
            self.logger.error(f"No permission to send message in {messageable}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error sending message: {e}")
            return None

    async def on_message(self, message: discord.Message):
        # Ignore bot messages and DMs
        if message.author.bot or not message.guild:
            return
        
        # Prevent duplicate processing
        message_key = f"{message.guild.id}-{message.id}"
        if message_key in self.processing_messages:
            return
        
        self.processing_messages.add(message_key)
        
        try:
            await self._process_message(message)
        finally:
            self.processing_messages.discard(message_key)

    async def _process_message(self, message: discord.Message):
        """Main message processing logic with proper error handling."""
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

        # Handle AI interactions first (highest priority)
        if is_mention:
            content = message.clean_content.replace(f"@{self.user.name}", "").strip()
            
            if content.lower().startswith(("summarize", "summary")):
                await self._handle_summarize_request(message)
                return
                
            # Regular AI conversation
            await self._handle_ai_conversation(message, is_mention=True)
            return

        if is_reply and feature_manager.is_feature_enabled(message.guild.id, "ai_chat"):
            await self._handle_ai_conversation(message, is_mention=False)
            return

        # Handle other features (in order of priority)
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
        
        # Process commands last
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
        """Handle conversation summarization with improved error handling."""
        feature_manager = self.get_cog("FeatureManager")
        if feature_manager and not feature_manager.is_feature_enabled(message.guild.id, "ai_summarize"):
            responses = [
                "The summarize feature is disabled here. Not my problem.",
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
            # Get recent message history with better filtering
            history = []
            async for msg in message.channel.history(limit=100, before=message):
                if (not msg.author.bot and 
                    msg.clean_content.strip() and 
                    len(msg.clean_content.strip()) > 3 and
                    not msg.clean_content.startswith('!')):  # Skip commands
                    history.append(f"{msg.author.display_name}: {msg.clean_content}")
                    
                if len(history) >= 30:  # Reasonable limit
                    break
                    
            if len(history) < 5:
                no_history_responses = [
                    "There's barely anything here to summarize. You want me to work with nothing?",
                    "What conversation? I don't see enough content worth summarizing.",
                    "You need more than a few messages for me to summarize something meaningful."
                ]
                return await self._send_with_realistic_timing(
                    message.channel, random.choice(no_history_responses),
                    reference_message=message, mention_author=False
                )

            history.reverse()  # Chronological order
            
            # Add a timeout for the summarization
            try:
                summary = await asyncio.wait_for(
                    self.gemini_service.summarize_conversation(history), 
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                return await self._send_with_realistic_timing(
                    message.channel, "That conversation was too complicated for my brain to process. Sorry.",
                    reference_message=message, mention_author=False
                )
            
            if summary:
                await self._send_with_realistic_timing(
                    message.channel, summary, 
                    reference_message=message, mention_author=False
                )
            else:
                await self._send_with_realistic_timing(
                    message.channel, "I couldn't make sense of that conversation. It was probably just chaos anyway.",
                    reference_message=message, mention_author=False
                )
            
        except Exception as e:
            self.logger.error(f"Summarization failed: {e}")
            error_responses = [
                "Something went wrong while I was trying to make sense of that mess.",
                "I couldn't summarize that for some reason. My brain just gave up.",
                "Yeah, that didn't work. The conversation was probably too weird for me to understand.",
                "My processing just... stopped. Can't help you with that one."
            ]
            await self._send_with_realistic_timing(
                message.channel, random.choice(error_responses),
                reference_message=message, mention_author=False
            )

    async def _handle_ai_conversation(self, message: discord.Message, is_mention: bool):
        """Handle AI conversation with improved error handling and rate limiting."""
        chat_cog = self.get_cog("AIChat")
        if not chat_cog or not chat_cog.gemini_service.is_ready():
            return

        user_id = message.author.id
        
        # Basic rate limiting to prevent spam
        last_message_time = self.last_message_times.get(user_id)
        if last_message_time:
            time_diff = (discord.utils.utcnow() - last_message_time).total_seconds()
            if time_diff < 2.0:  # 2-second cooldown
                return
        
        history = chat_cog.conversation_history[user_id]
        
        # Process the user's message
        if is_mention:
            user_message_content = message.clean_content.replace(f"@{self.user.name}", "").strip()
            if not user_message_content:  # Empty mention
                user_message_content = "Hi"
            # Don't clear history for mentions anymore - maintain context
        else:
            user_message_content = message.clean_content

        # Validate message content
        if not user_message_content or len(user_message_content.strip()) < 1:
            return

        # Add user message to history
        history.append({"role": "user", "parts": [user_message_content]})
        
        # Trim history to prevent context bloat
        if len(history) > 30:
            chat_cog.conversation_history[user_id] = history[-30:]
            history = chat_cog.conversation_history[user_id]

        try:
            # Generate response with timeout
            response_task = chat_cog.gemini_service.generate_chat_response(
                user_message=user_message_content,
                conversation_history=history,
                guild_id=message.guild.id,
                user_id=message.author.id
            )
            
            try:
                response_text = await asyncio.wait_for(response_task, timeout=25.0)
            except asyncio.TimeoutError:
                self.logger.warning(f"AI response timeout for user {user_id}")
                response_text = "Sorry, my brain just completely froze. Give me a second to reboot?"
            
            if not response_text or len(response_text.strip()) == 0:
                response_text = "I... completely lost my train of thought. What were we talking about?"
            
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
                "Sorry, what were we talking about? My brain just went blank.",
                "I completely lost my train of thought. What was the question?",
                "My thoughts are all scrambled right now. Can you repeat that?",
                "Something's definitely not working right up here. Try again maybe?"
            ]
            
            await self._send_with_realistic_timing(
                message.channel, random.choice(error_responses),
                reference_message=message, mention_author=False
            )