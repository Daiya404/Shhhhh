import os
import json
import asyncio
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Deque

import httpx
import discord
from discord.ext import commands
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# --- Data Classes for Configuration and State (Same as before) ---

@dataclass
class CharacterConfig:
    name: str = ""
    personality: str = ""
    description: str = ""
    traits: List[str] = field(default_factory=list)
    interests: List[str] = field(default_factory=list)

@dataclass
class KnowledgeSources:
    self_learning_urls: List[str] = field(default_factory=list)
    additional_context: str = ""

@dataclass
class ConversationSettings:
    max_history: int = 20 # Increased for multi-user context
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

# --- Chatbot "Brain" Class (Slightly modified) ---

class ChatbotBrain:
    def __init__(self, config: ChatbotConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.conversation_history: Deque[str] = Deque(maxlen=config.conversation_settings.max_history)
        self.knowledge = Knowledge()
        self.config_path = Path("config/chatbot_config.json")
        self.knowledge_path = Path("data/learned_knowledge.json")
        self.is_learning = False # A flag to prevent duplicate learning commands

    def load_knowledge(self):
        if self.knowledge_path.exists():
            try:
                with open(self.knowledge_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data['learned_urls'] = set(data.get('learned_urls', []))
                    self.knowledge = Knowledge(**data)
                print("Successfully loaded previous knowledge.")
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Warning: Could not load knowledge file. Error: {e}")
        
    def save_knowledge(self):
        self.knowledge_path.parent.mkdir(exist_ok=True)
        knowledge_dict = asdict(self.knowledge)
        knowledge_dict['learned_urls'] = list(self.knowledge.learned_urls)
        with open(self.knowledge_path, 'w', encoding='utf-8') as f:
            json.dump(knowledge_dict, f, indent=4)
        print("Knowledge saved successfully.")

    async def _call_gemini_api(self, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={self.gemini_api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            response = await self.client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (httpx.RequestError, KeyError, IndexError, json.JSONDecodeError) as e:
            print(f"Error calling Gemini API: {e}")
            return "Sorry, I had a little trouble thinking about that. Could you try again?"

    async def process_text_with_ai(self, content: str) -> str:
        prompt = (
            f"You are {self.config.character.name}. Process the following raw text, which contains information about you. "
            "Rewrite it in a natural, first-person perspective, focusing on your personality, background, and key characteristics. "
            "Clean up any irrelevant text, HTML, or script content.\n\n"
            f"Raw Text:\n---\n{content}\n---"
        )
        return await self._call_gemini_api(prompt)

    async def learn_from_url(self, url: str):
        if url in self.knowledge.learned_urls:
            print(f"Already learned from: {url}")
            return
        print(f"Fetching content from URL: {url}...")
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            response = await self.client.get(url, headers=headers, follow_redirects=True, timeout=20.0)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            for s in soup(['script', 'style']): s.decompose()
            content = soup.get_text(separator='\n', strip=True)
            if not content.strip(): return
            processed_content = await self.process_text_with_ai(content)
            if processed_content:
                fact_key = f"personal_knowledge_from_{Path(url).name}"
                self.knowledge.facts[fact_key] = processed_content
                self.knowledge.learned_urls.add(url)
                print(f"Successfully learned from: {url}")
        except Exception as e:
            print(f"Error fetching or processing URL {url}: {e}")

    async def learn_about_self(self):
        if self.is_learning: return
        self.is_learning = True
        print("\n--- Starting Self-Learning Process ---")
        self.load_knowledge()
        urls_to_learn = [url for url in self.config.knowledge_sources.self_learning_urls if url not in self.knowledge.learned_urls]
        if urls_to_learn:
            print(f"Learning from {len(urls_to_learn)} new configured URLs...")
            tasks = [self.learn_from_url(url) for url in urls_to_learn]
            await asyncio.gather(*tasks)
            self.save_knowledge()
        else:
            print("All configured URLs have already been learned.")
        print("--- Self-Learning Process Completed ---")
        self.is_learning = False
        
    def get_full_context(self) -> str:
        char = self.config.character
        context_parts = [
            f"You are a Discord chatbot named {char.name}.",
            f"Your personality: {char.personality}",
            f"Your core description: {char.description}",
            f"Your traits: {', '.join(char.traits)}.",
            f"Your interests: {', '.join(char.interests)}.",
        ]
        if self.knowledge.facts:
            context_parts.append("\n--- Your Learned Knowledge (respond from this first-person perspective) ---")
            for key, value in self.knowledge.facts.items():
                context_parts.append(f"Knowledge from {key.replace('_', ' ')}:\n{value}\n")
        if self.conversation_history:
            context_parts.append("\n--- Recent Conversation in this Channel ---")
            context_parts.extend(self.conversation_history)
        context_parts.append("\n--- Instructions ---")
        context_parts.append("Always stay in character. Use your learned knowledge to provide detailed and personal responses. Keep your responses concise and suitable for a chat format.")
        return "\n".join(context_parts)

    async def get_chat_response(self, user_input: str, author_name: str) -> str:
        history_entry = f"{author_name}: {user_input}"
        self.conversation_history.append(history_entry)
        context = self.get_full_context()
        prompt = f"{context}\n\n{history_entry}\n{self.config.character.name}:"
        bot_response = await self._call_gemini_api(prompt)
        self.conversation_history.append(f"{self.config.character.name}: {bot_response}")
        return bot_response

    def save_config(self):
        self.config_path.parent.mkdir(exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self.config), f, indent=4)
        print("Configuration saved successfully.")

# --- Discord Bot Setup ---

def load_or_create_config():
    config_path = Path("config/chatbot_config.json")
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return ChatbotConfig.from_dict(json.load(f))
    else:
        print("Config file not found! Please create 'config/chatbot_config.json' with your character's details.")
        # You could re-implement the interactive setup here if desired
        exit()

async def main():
    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN not found in .env file.")

    config = load_or_create_config()
    
    intents = discord.Intents.default()
    intents.message_content = True # Enable the message content intent
    
    bot = commands.Bot(command_prefix="!", intents=intents)
    
    # Create a single httpx client session and chatbot brain instance
    @bot.event
    async def setup_hook():
        bot.client = httpx.AsyncClient()
        bot.chatbot_brain = ChatbotBrain(config, bot.client)

    @bot.event
    async def on_ready():
        print(f'Logged in as {bot.user} (ID: {bot.user.id})')
        print('Bot is ready and running.')
        # Initial self-learning on startup
        await bot.chatbot_brain.learn_about_self()
        print(f"'{bot.chatbot_brain.config.character.name}' is online and ready to chat!")

    @bot.event
    async def on_message(message: discord.Message):
        # Ignore messages from the bot itself
        if message.author == bot.user:
            return

        # Process commands first
        await bot.process_commands(message)

        # Respond to mentions for conversation
        if bot.user.mentioned_in(message):
            # Use clean_content to remove the @mention from the input string
            user_input = message.clean_content.strip()
            author_name = message.author.display_name
            async with message.channel.typing():
                response = await bot.chatbot_brain.get_chat_response(user_input, author_name)
                await message.reply(response)
    
    # --- Bot Commands ---

    @bot.command(name='learn', help="Triggers the bot's self-learning process from configured URLs.")
    async def learn(ctx):
        if bot.chatbot_brain.is_learning:
            await ctx.send("I'm already in the middle of learning something! Please wait a moment.")
            return
        await ctx.send(f"Okay, I'll start my learning process. This might take a little while...")
        await bot.chatbot_brain.learn_about_self()
        await ctx.send("I've finished my study session! I feel a little smarter now.")

    @bot.command(name='addurl', help="Adds a new URL for the bot to learn from. Usage: !addurl <url>")
    async def add_url(ctx, url: str):
        bot.chatbot_brain.config.knowledge_sources.self_learning_urls.append(url)
        bot.chatbot_brain.save_config()
        await ctx.send(f"Thank you! I've added that URL to my reading list. I'll check it out the next time I `!learn`.")

    @bot.command(name='save', help="Saves the bot's current knowledge and config.")
    @commands.is_owner() # Only the bot owner can use this command
    async def save(ctx):
        bot.chatbot_brain.save_knowledge()
        bot.chatbot_brain.save_config()
        await ctx.send("I've saved my current memories and configuration.")
        
    # Run the bot
    await bot.start(token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot is shutting down.")