import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
import random
import time
import re
from typing import Dict, List, Optional

from .bot_admin import BotAdmin
# We import the type hint for our API cog for better code completion
from .anilist import AniListAPI

# --- Personality Responses for this Cog ---
PERSONALITY = {
    "channel_set": "Okay, the Word Game is now locked to {channel}. Don't make a mess.",
    "game_start": "A new Word Game has started! The first letter is **{letter}**. Let's see who's the fastest.",
    "correct_answer": "**{character_name}** is correct! The next letter is **{letter}**. You earned `{xp}` XP for that.",
    "already_used": "That name has already been used. Try to be more original.",
    "wrong_letter": "Wrong. The name has to start with **{letter}**. Pay attention.",
    "not_found": "I've never heard of that character. Are you making things up?",
    "no_game_active": "There's no game active. Start one with `/word-game start` in the right channel.",
    "list_empty": "No one has scored any points yet. Pathetic."
}

class WordGame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # This will be populated on_ready
        self.anilist_api: Optional[AniListAPI] = None

        self.settings_file = Path("data/role_settings.json") # Shared with other cogs
        self.scores_file = Path("data/word_game_scores.json")
        self.game_state_file = Path("data/word_game_state.json")

        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        self.scores_data: Dict[str, Dict[str, int]] = self._load_json(self.scores_file)
        # Data: {guild_id: {"last_letter": str, "last_timestamp": float, "used_names": [str]}}
        self.game_state: Dict[str, Dict] = self._load_json(self.game_state_file)

    @commands.Cog.listener()
    async def on_ready(self):
        """Get the AniListAPI cog once the bot is ready."""
        self.anilist_api = self.bot.get_cog("AniListAPI")
        if not self.anilist_api:
            self.logger.critical("CRITICAL: AniListAPI cog not found. The Word Game will not function.")

    # --- Data Handling ---
    def _load_json(self, file_path: Path) -> Dict:
        if not file_path.exists(): return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Error loading {file_path}", exc_info=True)
            return {}

    async def _save_json(self, data: dict, file_path: Path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except IOError as e:
            self.logger.error(f"Error saving {file_path}", exc_info=True)
            
    # --- Core Logic for Traffic Cop ---
    async def check_word_game_message(self, message: discord.Message) -> bool:
        """Checks a message to see if it's a valid word game submission."""
        if not self.anilist_api or not message.guild: return False

        guild_id = str(message.guild.id)
        game_channel_id = self.settings_data.get(guild_id, {}).get("word_game_channel_id")
        
        # Only operate in the designated game channel and if a game is active
        if not game_channel_id or message.channel.id != game_channel_id or guild_id not in self.game_state:
            return False

        # Ignore messages that look like commands
        if message.content.startswith(("/", "!", "?")): return False

        await self._process_game_submission(message)
        return True # We handled this message

    async def _process_game_submission(self, message: discord.Message):
        """The main logic for handling a potential answer."""
        guild_id = str(message.guild.id)
        state = self.game_state[guild_id]
        
        char_name = message.content.strip()
        
        # 1. Check if name was already used (case-insensitive)
        if char_name.lower() in [name.lower() for name in state["used_names"]]:
            return await message.reply(PERSONALITY["already_used"], delete_after=10)
            
        # 2. Check if it starts with the correct letter
        if self._get_first_letter(char_name) != state["last_letter"]:
            return await message.reply(PERSONALITY["wrong_letter"].format(letter=state["last_letter"].upper()), delete_after=10)
            
        # 3. Validate with AniList API
        async with message.channel.typing():
            character_data = await self.anilist_api.search_character(char_name)
        
        if not character_data:
            return await message.reply(PERSONALITY["not_found"], delete_after=10)

        # --- If all checks pass, it's a correct answer ---
        found_name = character_data["name"]["full"]
        
        # Calculate XP based on response time
        time_taken = time.time() - state["last_timestamp"]
        xp_gained = self._calculate_xp(time_taken)

        # Update scores
        self.scores_data.setdefault(guild_id, {})
        self.scores_data[guild_id].setdefault(str(message.author.id), 0)
        self.scores_data[guild_id][str(message.author.id)] += xp_gained
        
        # Update game state
        state["last_letter"] = self._get_last_letter(found_name)
        state["last_timestamp"] = time.time()
        state["used_names"].append(found_name)

        await self._save_json(self.scores_data, self.scores_file)
        await self._save_json(self.game_state, self.game_state_file)
        
        await message.reply(PERSONALITY["correct_answer"].format(
            character_name=found_name,
            letter=state["last_letter"].upper(),
            xp=xp_gained
        ))

    # --- Command Group ---
    game_group = app_commands.Group(name="word-game", description="Commands for the anime character word game.")

    @game_group.command(name="set-channel", description="Set the channel where the word game will be played.")
    @app_commands.describe(channel="The channel to lock the game to.")
    @BotAdmin.is_bot_admin()
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = str(interaction.guild.id)
        self.settings_data.setdefault(guild_id, {})["word_game_channel_id"] = channel.id
        await self._save_json(self.settings_data, self.settings_file)
        await interaction.response.send_message(PERSONALITY["channel_set"].format(channel=channel.mention), ephemeral=True)

    @game_group.command(name="start", description="Starts a new round of the word game.")
    async def start(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        game_channel_id = self.settings_data.get(guild_id, {}).get("word_game_channel_id")
        if not game_channel_id or interaction.channel_id != game_channel_id:
            return await interaction.response.send_message(f"This command can only be used in the designated game channel.", ephemeral=True)

        first_letter = random.choice("abcdefghijklmnopqrstuvwxyz")
        self.game_state[guild_id] = {
            "last_letter": first_letter,
            "last_timestamp": time.time(),
            "used_names": []
        }
        await self._save_json(self.game_state, self.game_state_file)
        await interaction.response.send_message(PERSONALITY["game_start"].format(letter=first_letter.upper()))

    @game_group.command(name="leaderboard", description="Show the word game leaderboard.")
    async def leaderboard(self, interaction: discord.Interaction):
        # ... (Implementation similar to other leaderboards)
        pass

    @game_group.command(name="stats", description="Check your personal score and rank in the word game.")
    async def stats(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        # ... (Implementation similar to other stats commands)
        pass
        
    # --- Helper Functions ---
    def _calculate_xp(self, time_taken: float) -> int:
        if time_taken <= 5: return 50
        if time_taken <= 15: return 25
        if time_taken <= 60: return 10
        return 5

    def _get_first_letter(self, name: str) -> str:
        name = re.sub(r'\W+', '', name.lower())
        return name[0] if name else ''

    def _get_last_letter(self, name: str) -> str:
        name = re.sub(r'\W+', '', name.lower())
        return name[-1] if name else ''

async def setup(bot):
    await bot.add_cog(WordGame(bot))