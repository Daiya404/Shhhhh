# core/bot.py - Enhanced message handling with AI reply tracking

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
        self.last_message_times = {}
        self.typing_delays = {}
        
        # Message handling state
        self.processing_messages = set()
        
        # This set is crucial for distinguishing AI chat messages from feature messages.
        self.ai_message_ids = set()

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
        typing_speed = 0.04
        thinking_time = min(1.5, response_length * 0.015)
        return base_time + (response_length * typing_speed) + thinking_time

    async def _send_with_realistic_timing(self, messageable, content: str, mention_author: bool = False, reference_message=None, is_ai_response: bool = False):
        """Send message with realistic timing and track AI responses."""
        if not content or len(content.strip()) == 0:
            self.logger.warning("Attempted to send empty message")
            return None
            
        if len(content) > 2000:
            self.logger.warning(f"Message too long ({len(content)} chars), truncating")
            content = content[:1950] + "\n\n...and I'm cutting myself off there."
        
        typing_time = self._calculate_realistic_typing_time(len(content))
        
        try:
            async with messageable.typing():
                await asyncio.sleep(min(typing_time, 4.0))
                
                if reference_message:
                    sent_message = await reference_message.reply(content, mention_author=mention_author)
                else:
                    sent_message = await messageable.send(content)
                
                # Only messages from the AI personality should be added to this set.
                if is_ai_response and sent_message:
                    self.ai_message_ids.add(sent_message.id)
                    if len(self.ai_message_ids) > 1000:
                        oldest_ids = list(self.ai_message_ids)[:100]
                        for old_id in oldest_ids:
                            self.ai_message_ids.discard(old_id)
                
                return sent_message
                    
        except discord.HTTPException as e:
            if e.code == 50035:
                self.logger.error(f"Discord message too long error: {len(content)} characters")
                truncated = content[:1500] + "\n\n...I have to cut this short. Discord won't let me finish."
                try:
                    if reference_message:
                        sent_message = await reference_message.reply(truncated, mention_author=mention_author)
                    else:
                        sent_message = await messageable.send(truncated)
                    
                    if is_ai_response and sent_message:
                        self.ai_message_ids.add(sent_message.id)
                    
                    return sent_message
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
        if message.author.bot or not message.guild:
            return
        
        message_key = f"{message.guild.id}-{message.id}"
        if message_key in self.processing_messages:
            return
        
        self.processing_messages.add(message_key)
        
        try:
            await self._process_message(message)
        finally:
            self.processing_messages.discard(message_key)

    def _is_reply_to_ai_message(self, message: discord.Message) -> bool:
        """
        STRICTLY checks if a message is a reply to another message that was
        specifically marked as an AI-generated conversational response.
        """
        if not (message.reference and isinstance(message.reference.resolved, discord.Message)):
            return False

        replied_message = message.reference.resolved
        is_author_bot = (replied_message.author == self.user)
        is_in_ai_set = (replied_message.id in self.ai_message_ids)
        
        return is_author_bot and is_in_ai_set

    async def _process_message(self, message: discord.Message):
        """Main message processing logic with a strict order of operations."""
        feature_manager = self.get_cog("FeatureManager")
        if not feature_manager:
            return

        is_mention = self.user.mentioned_in(message) and not message.mention_everyone
        is_valid_ai_reply = self._is_reply_to_ai_message(message)
        
        # --- 1. AI Interaction Logic ---

        # Case A: It's a valid reply to a previous AI conversation message.
        if is_valid_ai_reply:
            self.logger.info("AI trigger: Valid reply to a conversational message.")
            return await self._handle_ai_conversation(message, is_mention=is_mention)

        # Case B: It's a mention, but we must filter out replies to our own functional messages.
        if is_mention:
            is_reply_to_bot_at_all = (message.reference and
                                      isinstance(message.reference.resolved, discord.Message) and
                                      message.reference.resolved.author == self.user)
            
            # If it's a mention but NOT a reply to one of our own messages, it's a valid trigger.
            if not is_reply_to_bot_at_all:
                self.logger.info("AI trigger: Mention that is not a reply to the bot.")
                if message.clean_content.replace(f"@{self.user.name}", "").strip().lower().startswith(("summarize", "summary")):
                    return await self._handle_summarize_request(message)
                else:
                    return await self._handle_ai_conversation(message, is_mention=True)
            else:
                # It's a mention AND a reply to one of our messages, but we already know from
                # `is_valid_ai_reply` that it's NOT a conversational one. So, we ignore it.
                self.logger.info("Ignoring mention because it is a reply to a non-conversational bot message.")
                return

        # --- 2. Feature Block (runs only if no AI interaction occurred) ---
        if feature_manager.is_feature_enabled(message.guild.id, "detention_system"):
            if (detention_cog := self.get_cog("Detention")) and await detention_cog.is_user_detained(message):
                return await detention_cog.handle_detention_message(message)

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
        
        # --- 3. Command Block (Lowest Priority) ---
        await self.process_commands(message)
            
    async def on_ready(self):
        if not self.start_time:
            self.start_time = discord.utils.utcnow()
            
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
            responses = [ "The summarize feature is disabled here. Not my problem." ]
            return await self._send_with_realistic_timing(
                message.channel, random.choice(responses), 
                reference_message=message, mention_author=False, is_ai_response=True
            )
            
        if not self.gemini_service or not self.gemini_service.is_ready():
            error_responses = [ "My brain is offline. Can't summarize anything right now." ]
            return await self._send_with_realistic_timing(
                message.channel, random.choice(error_responses),
                reference_message=message, mention_author=False, is_ai_response=True
            )

        try:
            history = []
            async for msg in message.channel.history(limit=100, before=message):
                if (not msg.author.bot and 
                    msg.clean_content.strip() and 
                    len(msg.clean_content.strip()) > 3 and
                    not msg.clean_content.startswith('!')):
                    history.append(f"{msg.author.display_name}: {msg.clean_content}")
                    
                if len(history) >= 30:
                    break
                    
            if len(history) < 5:
                no_history_responses = [ "There's barely anything here to summarize. You want me to work with nothing?" ]
                return await self._send_with_realistic_timing(
                    message.channel, random.choice(no_history_responses),
                    reference_message=message, mention_author=False, is_ai_response=True
                )

            history.reverse()
            
            try:
                summary = await asyncio.wait_for(
                    self.gemini_service.summarize_conversation(history), 
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                summary = "That conversation was too complicated for my brain to process. Sorry."
            
            if summary:
                await self._send_with_realistic_timing(
                    message.channel, summary, 
                    reference_message=message, mention_author=False, is_ai_response=True
                )
            
        except Exception as e:
            self.logger.error(f"Summarization failed: {e}", exc_info=True)
            error_responses = [ "Something went wrong while I was trying to make sense of that mess." ]
            await self._send_with_realistic_timing(
                message.channel, random.choice(error_responses),
                reference_message=message, mention_author=False, is_ai_response=True
            )

    async def _handle_ai_conversation(self, message: discord.Message, is_mention: bool):
        """Handle AI conversation with improved error handling and rate limiting."""
        feature_manager = self.get_cog("FeatureManager")
        if not feature_manager or not feature_manager.is_feature_enabled(message.guild.id, "ai_chat"):
            return

        if not self.gemini_service or not self.gemini_service.is_ready():
            return await self._send_with_realistic_timing(
                message.channel, "My AI core isn't working right now. Try again later.",
                reference_message=message, mention_author=False, is_ai_response=True
            )

        user_id = message.author.id
        
        last_message_time = self.last_message_times.get(user_id)
        if last_message_time and (discord.utils.utcnow() - last_message_time).total_seconds() < 2.0:
            self.logger.debug(f"Rate limited user {user_id} for AI chat.")
            return
        
        self.last_message_times[user_id] = discord.utils.utcnow()

        chat_cog = self.get_cog("AIChat")
        history = chat_cog.conversation_history[user_id] if chat_cog else self.bot._conversation_histories.setdefault(user_id, [])

        user_message_content = message.clean_content.replace(f"@{self.user.name}", "").strip() if is_mention else message.clean_content
        if not user_message_content:
            user_message_content = "Hi"

        history.append({"role": "user", "parts": [user_message_content]})
        if len(history) > 30:
            history = history[-30:]
            if chat_cog: chat_cog.conversation_history[user_id] = history
            else: self.bot._conversation_histories[user_id] = history

        try:
            response_task = self.gemini_service.generate_chat_response(
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
            
            if not response_text or not response_text.strip():
                self.logger.warning(f"AI returned an empty response for user {user_id}.")
                response_text = "I... completely lost my train of thought. What were we talking about?"
            
            history.append({"role": "model", "parts": [response_text]})
            if chat_cog: chat_cog.conversation_history[user_id] = history
            else: self.bot._conversation_histories[user_id] = history
            
            await self._send_with_realistic_timing(
                message.channel, response_text,
                reference_message=message, mention_author=False, is_ai_response=True
            )
            
        except Exception as e:
            self.logger.error(f"AI conversation failed unexpectedly: {e}", exc_info=True)
            error_responses = [ "My thoughts are all scrambled right now. Can you repeat that?" ]
            
            await self._send_with_realistic_timing(
                message.channel, random.choice(error_responses),
                reference_message=message, mention_author=False, is_ai_response=True
            )