import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
from pathlib import Path
import logging
import re
import asyncio
from typing import Dict, List, Deque
from dataclasses import dataclass, field, asdict
import httpx
from bs4 import BeautifulSoup
import os

from .bot_admin import BotAdmin

# --- Data Classes (Unchanged) ---
@dataclass
class CharacterConfig:
    name: str = "Tika"
    personality: str = ""
    description: str = ""
    traits: List[str] = field(default_factory=list)
    interests: List[str] = field(default_factory=list)
# ... (The rest of the dataclasses are correct and unchanged)
@dataclass
class KnowledgeSources:
    self_learning_urls: List[str] = field(default_factory=list)
    additional_context: str = ""
@dataclass
class ConversationSettings:
    max_history: int = 20
    learning_frequency: str = "daily"
@dataclass
class ChatbotConfig:
    character: CharacterConfig = field(default_factory=CharacterConfig)
    knowledge_sources: KnowledgeSources = field(default_factory=KnowledgeSources)
    conversation_settings: ConversationSettings = field(default_factory=ConversationSettings)
    @classmethod
    def from_dict(cls, d):
        return cls(
            character=CharacterConfig(**d.get('character', {})),
            knowledge_sources=KnowledgeSources(**d.get('knowledge_sources', {})),
            conversation_settings=ConversationSettings(**d.get('conversation_settings', {}))
        )
@dataclass
class Knowledge:
    facts: Dict[str, str] = field(default_factory=dict)
    learned_urls: set[str] = field(default_factory=set)
    search_history: List[str] = field(default_factory=list)

# --- ChatbotBrain Class (Optimized with per-channel history) ---
class ChatbotBrain:
    def __init__(self, config: ChatbotConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        # --- NEW: Per-channel conversation history ---
        self.conversation_histories: Dict[int, Deque[str]] = {}
        self.knowledge = Knowledge()
        self.config_path = Path("config/chatbot_config.json")
        self.knowledge_path = Path("data/learned_knowledge.json")
        self.is_learning = False

    def get_history_for_channel(self, channel_id: int) -> Deque[str]:
        """Gets or creates a conversation history deque for a specific channel."""
        if channel_id not in self.conversation_histories:
            self.conversation_histories[channel_id] = Deque(maxlen=self.config.conversation_settings.max_history)
        return self.conversation_histories[channel_id]

    # ... (load/save knowledge, api calls are unchanged)
    def load_knowledge(self):
        if self.knowledge_path.exists():
            try:
                with open(self.knowledge_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data['learned_urls'] = set(data.get('learned_urls', []))
                    self.knowledge = Knowledge(**data)
            except (json.JSONDecodeError, TypeError) as e:
                logging.warning(f"Could not load knowledge file. Error: {e}")
    def save_knowledge(self):
        self.knowledge_path.parent.mkdir(exist_ok=True)
        knowledge_dict = asdict(self.knowledge)
        knowledge_dict['learned_urls'] = list(self.knowledge.learned_urls)
        with open(self.knowledge_path, 'w', encoding='utf-8') as f:
            json.dump(knowledge_dict, f, indent=4)
    async def _call_gemini_api(self, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={self.gemini_api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            response = await self.client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            logging.error(f"Error calling Gemini API: {e}", exc_info=True)
            return "Sorry, I had a little trouble thinking. Could you try again?"
    async def process_text_with_ai(self, content: str) -> str:
        prompt = (f"You are {self.config.character.name}. Process raw text from a webpage. "
                  "Rewrite it in your own first-person voice, summarizing key info about your background or abilities. "
                  "Ignore irrelevant content like ads or scripts.\n\n"
                  f"Raw Text:\n---\n{content}\n---")
        return await self._call_gemini_api(prompt)
    async def learn_from_url(self, url: str):
        if url in self.knowledge.learned_urls: return
        logging.info(f"Chatbot: Learning from URL: {url}...")
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            response = await self.client.get(url, headers=headers, follow_redirects=True, timeout=20.0)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            for s in soup(['script', 'style']): s.decompose()
            content = soup.get_text(separator='\n', strip=True)
            if not content.strip(): return
            processed_content = await self.process_text_with_ai(content)
            if processed_content:
                fact_key = f"knowledge_from_{Path(url).name}"
                self.knowledge.facts[fact_key] = processed_content
                self.knowledge.learned_urls.add(url)
        except Exception as e:
            logging.error(f"Error fetching or processing URL {url}: {e}", exc_info=True)
    async def learn_about_self(self):
        if self.is_learning: return
        self.is_learning = True
        self.load_knowledge()
        urls_to_learn = [url for url in self.config.knowledge_sources.self_learning_urls if url not in self.knowledge.learned_urls]
        if urls_to_learn:
            tasks = [self.learn_from_url(url) for url in urls_to_learn]
            await asyncio.gather(*tasks)
            self.save_knowledge()
        self.is_learning = False
        
    def get_full_context(self, channel_id: int) -> str:
        char = self.config.character
        history = self.get_history_for_channel(channel_id)
        context = [f"You are a Discord chatbot named Tika. Personality: {char.personality}",
                   f"Description: {char.description}", f"Traits: {', '.join(char.traits)}"]
        if self.knowledge.facts:
            context.append("\n--- Your Learned Knowledge (respond in first-person) ---")
            context.extend(self.knowledge.facts.values())
        if history:
            context.append("\n--- Recent Conversation ---")
            context.extend(history)
        context.append("\n--- Instructions ---\nStay in character. Keep responses concise for chat.")
        return "\n".join(context)

    async def get_chat_response(self, user_input: str, author_name: str, channel_id: int) -> str:
        history = self.get_history_for_channel(channel_id)
        history.append(f"{author_name}: {user_input}")
        
        context = self.get_full_context(channel_id)
        prompt = f"{context}\n\n{author_name}: {user_input}\n{self.config.character.name}:"
        
        bot_response = await self._call_gemini_api(prompt)
        history.append(f"{self.config.character.name}: {bot_response}")
        return bot_response

    def save_config(self):
        self.config_path.parent.mkdir(exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self.config), f, indent=4)

# --- The Main Cog Class ---
class Chatbot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.config_path = Path("config/chatbot_config.json")
        self.chatbot_brain = None

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.chatbot_brain:
            client = httpx.AsyncClient()
            config = self._load_or_create_config()
            self.chatbot_brain = ChatbotBrain(config, client)
            self.logger.info("Chatbot brain initialized. Starting first self-learning session...")
            await self.chatbot_brain.learn_about_self()
            self.logger.info("Chatbot self-learning complete.")

    def _load_or_create_config(self) -> ChatbotConfig:
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return ChatbotConfig.from_dict(json.load(f))
        else:
            self.logger.warning("`config/chatbot_config.json` not found! Creating default.")
            default_config = ChatbotConfig()
            self.config_path.parent.mkdir(exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(default_config), f, indent=4)
            return default_config

    # --- Public method for bot.py to call (RENAMED) ---
    async def handle_mention(self, message: discord.Message):
        """Called by the Traffic Cop when the bot is mentioned."""
        if not self.chatbot_brain or not self.bot.user.mentioned_in(message):
            return

        user_input = message.clean_content.strip()
        author_name = message.author.display_name
        async with message.channel.typing():
            response = await self.chatbot_brain.get_chat_response(user_input, author_name, message.channel.id)
            await message.reply(response)

    # --- Converted Slash Commands (Unchanged) ---
    chatbot_group = app_commands.Group(name="chatbot", description="Commands to manage Tika's AI brain.")
    @chatbot_group.command(name="learn", description="Trigger the self-learning process from configured URLs.")
    @BotAdmin.is_bot_admin()
    async def learn(self, interaction: discord.Interaction):
        if not self.chatbot_brain: return await interaction.response.send_message("My brain isn't ready yet.", ephemeral=True)
        if self.chatbot_brain.is_learning: return await interaction.response.send_message("I'm already learning something!", ephemeral=True)
        await interaction.response.send_message("Okay, starting my study session...", ephemeral=True)
        await self.chatbot_brain.learn_about_self()
        await interaction.followup.send("I've finished studying.", ephemeral=True)
    @chatbot_group.command(name="add-url", description="Add a new URL for the bot to learn from.")
    @app_commands.describe(url="The URL to add to the reading list.")
    @BotAdmin.is_bot_admin()
    async def add_url(self, interaction: discord.Interaction, url: str):
        if not self.chatbot_brain: return await interaction.response.send_message("My brain isn't ready yet.", ephemeral=True)
        self.chatbot_brain.config.knowledge_sources.self_learning_urls.append(url)
        self.chatbot_brain.save_config()
        await interaction.response.send_message("Thanks. I've added that to my reading list.", ephemeral=True)
    @chatbot_group.command(name="save", description="Save the bot's current knowledge and config.")
    @BotAdmin.is_bot_admin()
    async def save(self, interaction: discord.Interaction):
        if not self.chatbot_brain: return await interaction.response.send_message("My brain isn't ready yet.", ephemeral=True)
        self.chatbot_brain.save_knowledge()
        self.chatbot_brain.save_config()
        await interaction.response.send_message("I've saved my current memories and configuration.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Chatbot(bot))