import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
import asyncio
from typing import Dict, List, Deque, Optional
from dataclasses import dataclass, field, asdict
import httpx
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv

from .bot_admin import BotAdmin

# Load environment variables from .env file
load_dotenv()

# --- Data Classes for Configuration ---
@dataclass
class CharacterConfig:
    name: str = "Tika"; personality: str = ""; description: str = ""
    traits: List[str] = field(default_factory=list); interests: List[str] = field(default_factory=list)
@dataclass
class KnowledgeSources:
    self_learning_urls: List[str] = field(default_factory=list); additional_context: str = ""
@dataclass
class ConversationSettings:
    max_history: int = 20; learning_frequency: str = "daily"
@dataclass
class ChatbotConfig:
    character: CharacterConfig = field(default_factory=CharacterConfig)
    knowledge_sources: KnowledgeSources = field(default_factory=KnowledgeSources)
    conversation_settings: ConversationSettings = field(default_factory=ConversationSettings)
    @classmethod
    def from_dict(cls, d):
        return cls(character=CharacterConfig(**d.get('character',{})), knowledge_sources=KnowledgeSources(**d.get('knowledge_sources',{})), conversation_settings=ConversationSettings(**d.get('conversation_settings',{})))
@dataclass
class Knowledge:
    facts: Dict[str, str] = field(default_factory=dict)
    learned_urls: set[str] = field(default_factory=set)

# --- The AI "Brain" ---
class ChatbotBrain:
    def __init__(self, config: ChatbotConfig, client: httpx.AsyncClient):
        self.config = config; self.client = client
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.conversation_histories: Dict[int, Deque[str]] = {}
        self.knowledge = Knowledge()
        self.config_path = Path("config/chatbot_config.json")
        self.knowledge_path = Path("data/learned_knowledge.json")
        self.is_learning = False

    def get_history_for_channel(self, channel_id: int) -> Deque[str]:
        if channel_id not in self.conversation_histories:
            self.conversation_histories[channel_id] = Deque(maxlen=self.config.conversation_settings.max_history)
        return self.conversation_histories[channel_id]

    def load_knowledge(self):
        if self.knowledge_path.exists():
            try:
                with open(self.knowledge_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data['learned_urls'] = set(data.get('learned_urls', []))
                    self.knowledge = Knowledge(**data)
            except (json.JSONDecodeError, TypeError): pass
    def save_knowledge(self):
        self.knowledge_path.parent.mkdir(exist_ok=True)
        knowledge_dict = asdict(self.knowledge)
        knowledge_dict['learned_urls'] = list(self.knowledge.learned_urls)
        with open(self.knowledge_path, 'w', encoding='utf-8') as f:
            json.dump(knowledge_dict, f, indent=2)

    async def _call_gemini_api(self, prompt: str) -> str:
        if not self.gemini_api_key: return "My AI brain is missing its API key. An admin needs to fix this."
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={self.gemini_api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            response = await self.client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception:
            logging.error(f"Error calling Gemini API.", exc_info=True)
            return "Sorry, I had a little trouble thinking. Could you try again?"

    async def process_text_with_ai(self, content: str) -> str:
        prompt = (f"You are {self.config.character.name}. Process raw text from a webpage. "
                  "Rewrite it in your own first-person voice, summarizing key info about your background or abilities. "
                  "Ignore irrelevant content.\n\n" f"Raw Text:\n---\n{content}\n---")
        return await self._call_gemini_api(prompt)

    async def learn_from_url(self, url: str):
        if url in self.knowledge.learned_urls: return
        logging.info(f"Chatbot: Learning from URL: {url}...")
        try:
            response = await self.client.get(url, follow_redirects=True, timeout=20.0)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            for s in soup(['script', 'style']): s.decompose()
            content = soup.get_text(separator='\n', strip=True)
            if content.strip():
                processed_content = await self.process_text_with_ai(content)
                self.knowledge.facts[f"knowledge_from_{Path(url).name}"] = processed_content
                self.knowledge.learned_urls.add(url)
        except Exception:
            logging.error(f"Error fetching or processing URL {url}", exc_info=True)

    async def learn_about_self(self):
        if self.is_learning: return
        self.is_learning = True
        self.load_knowledge()
        urls_to_learn = [url for url in self.config.knowledge_sources.self_learning_urls if url not in self.knowledge.learned_urls]
        if urls_to_learn:
            await asyncio.gather(*[self.learn_from_url(url) for url in urls_to_learn])
            self.save_knowledge()
        self.is_learning = False
        
    def get_full_context(self, history: List[str]) -> str:
        char = self.config.character
        context = [f"You are a Discord chatbot named Tika. Personality: {char.personality}",
                   f"Description: {char.description}", f"Traits: {', '.join(char.traits)}"]
        if self.knowledge.facts:
            context.append("\n--- Your Learned Knowledge (respond in first-person) ---")
            context.extend(self.knowledge.facts.values())
        if history:
            context.append("\n--- Current Conversation ---")
            context.extend(history)
        context.append("\n--- Instructions ---\nStay in character. Keep responses concise for chat.")
        return "\n".join(context)

    async def get_chat_response(self, user_input: str, author_name: str, channel_id: int, history_override: List[str]) -> str:
        prompt_history = history_override + [f"{author_name}: {user_input}"]
        context = self.get_full_context(prompt_history)
        prompt = f"{context}\n{self.config.character.name}:"
        bot_response = await self._call_gemini_api(prompt)
        
        channel_memory = self.get_history_for_channel(channel_id)
        channel_memory.append(f"{author_name}: {user_input}")
        channel_memory.append(f"{self.config.character.name}: {bot_response}")
        return bot_response

    def save_config(self):
        self.config_path.parent.mkdir(exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self.config), f, indent=2)

# --- The Main Cog Class ---
class Chatbot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.config_path = Path("config/chatbot_config.json")
        self.chatbot_brain: Optional[ChatbotBrain] = None

    @commands.Cog.listener()
    async def on_ready(self):
        await asyncio.sleep(1) # Wait for other cogs to be available
        if not self.chatbot_brain:
            client = httpx.AsyncClient()
            config = self._load_or_create_config()
            self.chatbot_brain = ChatbotBrain(config, client)
            self.logger.info("Chatbot brain initialized. Starting self-learning...")
            await self.chatbot_brain.learn_about_self()
            self.logger.info("Chatbot self-learning complete.")

    def _load_or_create_config(self) -> ChatbotConfig:
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return ChatbotConfig.from_dict(json.load(f))
        else:
            default_config = ChatbotConfig()
            default_config.save_config()
            return default_config

    # --- Public method for bot.py to call ---
    async def handle_mention(self, message: discord.Message) -> bool:
        if not self.chatbot_brain or not self.bot.user.mentioned_in(message) or message.reference:
            return False

        context_history = [f"{m.author.display_name}: {m.clean_content}" async for m in message.channel.history(limit=5, before=message)]
        context_history.reverse()
        
        async with message.channel.typing():
            response = await self.chatbot_brain.get_chat_response(
                user_input=message.clean_content, 
                author_name=message.author.display_name, 
                channel_id=message.channel.id,
                history_override=context_history
            )
            await message.reply(response)
        return True

    # --- Converted Slash Commands ---
    chatbot_group = app_commands.Group(name="chatbot", description="Commands to manage Tika's AI brain.")

    @chatbot_group.command(name="summarize", description="Use AI to summarize recent messages in this channel.")
    @app_commands.describe(count="The number of messages to summarize (max 100).")
    async def summarize(self, i: discord.Interaction, count: app_commands.Range[int, 5, 100]):
        if not self.chatbot_brain: return await i.response.send_message("My brain isn't working.", ephemeral=True)
        await i.response.send_message(f"Fine, I'll catch you up. Reading the last {count} messages...", ephemeral=True)
        history = [f"{m.author.display_name}: {m.clean_content}" async for m in i.channel.history(limit=count)]
        history.reverse()
        chat_log = "\n".join(history)
        prompt = (
            "You are a helpful assistant named Tika. Summarize the following Discord chat log. "
            "Provide a concise, bulleted summary of the main topics and conclusions. "
            "Ignore casual chatter.\n\n" f"Chat Log:\n---\n{chat_log}\n---"
        )
        summary = await self.chatbot_brain._call_gemini_api(prompt)
        embed = discord.Embed(title=f"Summary of the Last {count} Messages", description=summary, color=discord.Color.blue())
        await i.followup.send(embed=embed, ephemeral=True)

    @chatbot_group.command(name="learn", description="Trigger the self-learning process from configured URLs.")
    @BotAdmin.is_bot_admin()
    async def learn(self, i: discord.Interaction):
        if not self.chatbot_brain or self.chatbot_brain.is_learning: return await i.response.send_message("I'm already learning!", ephemeral=True)
        await i.response.send_message("Okay, starting my study session...", ephemeral=True)
        await self.chatbot_brain.learn_about_self()
        await i.followup.send("I've finished studying.", ephemeral=True)

    @chatbot_group.command(name="add-url", description="Add a new URL for the bot to learn from.")
    @app_commands.describe(url="The URL to add to the reading list.")
    @BotAdmin.is_bot_admin()
    async def add_url(self, i: discord.Interaction, url: str):
        if not self.chatbot_brain: return
        self.chatbot_brain.config.knowledge_sources.self_learning_urls.append(url)
        self.chatbot_brain.save_config()
        await i.response.send_message("Thanks. I've added that to my reading list.", ephemeral=True)

    @chatbot_group.command(name="save", description="Save the bot's current knowledge and config.")
    @BotAdmin.is_bot_admin()
    async def save(self, i: discord.Interaction):
        if not self.chatbot_brain: return
        self.chatbot_brain.save_knowledge()
        self.chatbot_brain.save_config()
        await i.response.send_message("I've saved my memories and configuration.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Chatbot(bot))