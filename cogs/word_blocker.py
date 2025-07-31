import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
import re
from typing import Dict, List, Set

# Import the custom admin check from our other cog
from .bot_admin import BotAdmin

# --- Personality Responses for this Cog ---
PERSONALITY = {
    "word_added": "Noted. I will now watch for that word.",
    "word_removed": "Fine, I've removed that word from the blocklist.",
    "already_blocked": "I'm already blocking that word. Are you even paying attention?",
    "not_blocked": "I wasn't blocking that word to begin with. Try to keep up.",
    "list_empty": "There are no words on the blocklist. The server is pure, for now.",
    # This response is now sent in-channel
    "channel_warning": "{user}, your message contained a blocked term and was deleted. Watch it."
}

class WordBlocker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.blocklist_file = Path("data/word_blocklist.json")
        
        # Data structure: {guild_id: {"global": [words], "users": {user_id: [words]}}}
        self.blocklist_data: Dict[str, Dict[str, any]] = self._load_json()
        
        # Cache for compiled regex patterns for maximum efficiency
        self.regex_cache: Dict[str, Dict[str, any]] = {}
        self._build_all_regex_caches()

    # --- Data and Cache Management ---
    def _load_json(self) -> Dict:
        if not self.blocklist_file.exists(): return {}
        try:
            with open(self.blocklist_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            self.logger.error(f"Error loading {self.blocklist_file}", exc_info=True)
            return {}

    async def _save_json(self):
        try:
            with open(self.blocklist_file, 'w', encoding='utf-8') as f:
                json.dump(self.blocklist_data, f, indent=2)
        except IOError:
            self.logger.error(f"Error saving {self.blocklist_file}", exc_info=True)

    def _build_all_regex_caches(self):
        """Builds the regex cache for all guilds on startup."""
        self.logger.info("Building word block regex caches...")
        for guild_id, data in self.blocklist_data.items():
            self._update_regex_for_guild(guild_id)

    def _update_regex_for_guild(self, guild_id: str):
        """Compiles and caches the regex for a specific guild's blocklists."""
        if guild_id not in self.regex_cache:
            self.regex_cache[guild_id] = {"global": None, "users": {}}

        guild_data = self.blocklist_data.get(guild_id, {})
        self.regex_cache[guild_id]["global"] = self._compile_word_list(guild_data.get("global", []))
        user_lists = guild_data.get("users", {})
        for user_id, words in user_lists.items():
            self.regex_cache[guild_id]["users"][user_id] = self._compile_word_list(words)

    def _compile_word_list(self, words: List[str]) -> re.Pattern | None:
        """Takes a list of words and returns a compiled regex object."""
        if not words: return None
        pattern = r'\b(' + '|'.join(re.escape(word) for word in words) + r')\b'
        return re.compile(pattern, re.IGNORECASE)

    # --- Core Message Listener ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return
        if message.author.guild_permissions.administrator:
            return

        guild_id_str = str(message.guild.id)
        user_id_str = str(message.author.id)
        guild_cache = self.regex_cache.get(guild_id_str)
        if not guild_cache: return

        # Check global and then user-specific lists
        global_regex = guild_cache.get("global")
        user_regex = guild_cache.get("users", {}).get(user_id_str)

        if  (global_regex and global_regex.search(message.content)) or \
            (user_regex and user_regex.search(message.content)):
            await self._handle_blocked_message(message)
            return

    async def _handle_blocked_message(self, message: discord.Message):
        """
        Deletes the message and sends a temporary, public warning in the same channel.
        """
        try:
            await message.delete()
            # Send the warning message in the same channel, mentioning the user.
            # It will auto-delete after 10 seconds to keep the channel clean.
            warning_text = PERSONALITY["channel_warning"].format(user=message.author.mention)
            await message.channel.send(warning_text, delete_after=10)
        except discord.Forbidden:
            self.logger.warning(f"Failed to delete message or send warning in {message.channel.name}.")
        except discord.NotFound:
            pass # Message was already deleted.

    # --- Command Structure ---
    blocklist_group = app_commands.Group(name="blocklist", description="Manage the server's word blocklist.")
    global_group = app_commands.Group(name="global", parent=blocklist_group, description="Manage globally blocked words.")
    user_group = app_commands.Group(name="user", parent=blocklist_group, description="Manage user-specific blocked words.")

    # --- Helper Logic for Commands (add, remove, list) ---
    async def _modify_words(self, interaction: discord.Interaction, action: str, scope: str, words_str: str, user: discord.Member = None):
        """A single helper to handle adding and removing words for both scopes."""
        guild_id_str = str(interaction.guild_id)
        user_id_str = str(user.id) if user else None
        words = {word for word in words_str.lower().split() if word} # Use a set for efficiency

        if not words:
            await interaction.response.send_message("You have to actually provide words.", ephemeral=True)
            return
            
        # Ensure data structure exists
        self.blocklist_data.setdefault(guild_id_str, {"global": [], "users": {}})
        if user_id_str:
            self.blocklist_data[guild_id_str]["users"].setdefault(user_id_str, [])

        # Get the specific word list we're modifying
        if scope == "global":
            word_list = self.blocklist_data[guild_id_str]["global"]
        else: # scope == "user"
            word_list = self.blocklist_data[guild_id_str]["users"][user_id_str]
        
        word_set = set(word_list)
        
        if action == "add":
            changed_words = words - word_set
            if not changed_words:
                await interaction.response.send_message(PERSONALITY["already_blocked"], ephemeral=True)
                return
            word_set.update(changed_words)
            response_template = PERSONALITY["word_added"]
        else: # action == "remove"
            changed_words = words & word_set
            if not changed_words:
                await interaction.response.send_message(PERSONALITY["not_blocked"], ephemeral=True)
                return
            word_set.difference_update(changed_words)
            response_template = PERSONALITY["word_removed"]
            
        # Update the original list
        if scope == "global":
            self.blocklist_data[guild_id_str]["global"] = sorted(list(word_set))
        else:
            self.blocklist_data[guild_id_str]["users"][user_id_str] = sorted(list(word_set))

        await self._save_json()
        self._update_regex_for_guild(guild_id_str)
        
        user_prefix = f"For **{user.display_name}**: " if user else ""
        await interaction.response.send_message(f"{user_prefix}{response_template} Words: `{'`, `'.join(sorted(changed_words))}`", ephemeral=True)

    # --- Global Commands ---
    @global_group.command(name="add", description="Add one or more globally blocked words.")
    @app_commands.describe(words="The word(s) to block, separated by spaces.")
    @BotAdmin.is_bot_admin()
    async def global_add(self, interaction: discord.Interaction, words: str):
        await self._modify_words(interaction, "add", "global", words)

    @global_group.command(name="remove", description="Remove one or more globally blocked words.")
    @app_commands.describe(words="The word(s) to unblock, separated by spaces.")
    @BotAdmin.is_bot_admin()
    async def global_remove(self, interaction: discord.Interaction, words: str):
        await self._modify_words(interaction, "remove", "global", words)

    @global_group.command(name="list", description="List all globally blocked words.")
    @BotAdmin.is_bot_admin()
    async def global_list(self, interaction: discord.Interaction):
        words = self.blocklist_data.get(str(interaction.guild_id), {}).get("global", [])
        if not words:
            await interaction.response.send_message(PERSONALITY["list_empty"], ephemeral=True)
            return
        embed = discord.Embed(title="Globally Blocked Words", description=", ".join(f"`{w}`" for w in words), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- User-Specific Commands ---
    @user_group.command(name="add", description="Add user-specific blocked words.")
    @app_commands.describe(user="The user to block words for.", words="The word(s) to block.")
    @BotAdmin.is_bot_admin()
    async def user_add(self, interaction: discord.Interaction, user: discord.Member, words: str):
        await self._modify_words(interaction, "add", "user", words, user)

    @user_group.command(name="remove", description="Remove user-specific blocked words.")
    @app_commands.describe(user="The user to unblock words for.", words="The word(s) to unblock.")
    @BotAdmin.is_bot_admin()
    async def user_remove(self, interaction: discord.Interaction, user: discord.Member, words: str):
        await self._modify_words(interaction, "remove", "user", words, user)
    
    @user_group.command(name="list", description="List all blocked words for a specific user.")
    @app_commands.describe(user="The user whose list you want to see.")
    @BotAdmin.is_bot_admin()
    async def user_list(self, interaction: discord.Interaction, user: discord.Member):
        words = self.blocklist_data.get(str(interaction.guild_id), {}).get("users", {}).get(str(user.id), [])
        if not words:
            await interaction.response.send_message(f"No specific words are blocked for **{user.display_name}**.", ephemeral=True)
            return
        embed = discord.Embed(title=f"Blocked Words for {user.display_name}", description=", ".join(f"`{w}`" for w in words), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(WordBlocker(bot))