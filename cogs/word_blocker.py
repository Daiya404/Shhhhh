import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
from typing import Dict, List, Set
import logging

class WordBlocker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_dir = 'data'
        self.blocked_words_file = os.path.join(self.data_dir, 'blocked_words.json')
        self.blocked_words: Dict[str, Set[str]] = {}
        self._file_lock = asyncio.Lock()
        
        # Performance optimization: cache for faster lookups
        self._users_with_blocks: Set[str] = set()
        
        # Ensure data directory exists and load data
        self._ensure_data_directory()
        self._load_blocked_words()
        
        # Setup logging
        self.logger = logging.getLogger(__name__)

    def _ensure_data_directory(self):
        """Ensure the data directory exists"""
        os.makedirs(self.data_dir, exist_ok=True)

    def _load_blocked_words(self):
        """Load blocked words from JSON file with error handling"""
        if not os.path.exists(self.blocked_words_file):
            return
        
        try:
            with open(self.blocked_words_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Convert lists to sets for O(1) lookup performance
                self.blocked_words = {
                    user_id: set(words) for user_id, words in data.items()
                }
                self._users_with_blocks = set(self.blocked_words.keys())
        except (json.JSONDecodeError, FileNotFoundError) as e:
            self.logger.error(f"Error loading blocked words: {e}")
            self.blocked_words = {}
            self._users_with_blocks = set()

    async def _save_blocked_words(self):
        """Save blocked words to JSON file asynchronously with file locking"""
        async with self._file_lock:
            try:
                # Convert sets back to lists for JSON serialization
                data_to_save = {
                    user_id: list(words) for user_id, words in self.blocked_words.items()
                }
                
                # Write to temporary file first, then rename for atomic operation
                temp_file = self.blocked_words_file + '.tmp'
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data_to_save, f, indent=2, ensure_ascii=False)
                
                # Atomic rename
                os.replace(temp_file, self.blocked_words_file)
                
            except Exception as e:
                self.logger.error(f"Error saving blocked words: {e}")

    async def check_blocked_words(self, message: discord.Message) -> bool:
        """Optimized blocked word checking with early returns"""
        if message.author.bot:
            return False
        
        user_id = str(message.author.id)
        
        # Fast path: check if user has any blocked words
        if user_id not in self._users_with_blocks:
            return False
        
        blocked_words_for_user = self.blocked_words.get(user_id)
        if not blocked_words_for_user:
            return False
        
        message_content = message.content.lower()
        
        # Use any() for early termination
        if any(word in message_content for word in blocked_words_for_user):
            return await self._handle_blocked_message(message)
        
        return False

    async def _handle_blocked_message(self, message: discord.Message) -> bool:
        """Handle a message containing blocked words"""
        try:
            await message.delete()
            
            # Send warning with auto-delete
            warning_msg = await message.channel.send(
                f"🚫 {message.author.mention}, your message contained a blocked word and was deleted.",
                delete_after=5
            )
            return True
            
        except discord.NotFound:
            # Message already deleted
            return True
        except discord.Forbidden:
            # No permission to delete
            self.logger.warning(f"No permission to delete message from {message.author}")
            return False

    @app_commands.command(name="blockword", description="Add a blocked word for a specific user")
    @app_commands.describe(
        user="The user to block the word for",
        word="The word to block"
    )
    async def block_word(
        self, 
        interaction: discord.Interaction, 
        user: discord.Member, 
        word: str
    ):
        """Add a word to the blocked list for a specific user"""
        
        if not self._check_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You need administrator permissions to use this command!",
                ephemeral=True
            )
            return
        
        # Validate and normalize word
        normalized_word = self._validate_and_normalize_word(word)
        if not normalized_word:
            await interaction.response.send_message(
                "❌ Please provide a valid word to block!",
                ephemeral=True
            )
            return
        
        user_id = str(user.id)
        
        # Initialize user's blocked words set if needed
        if user_id not in self.blocked_words:
            self.blocked_words[user_id] = set()
            self._users_with_blocks.add(user_id)
        
        # Check if word is already blocked
        if normalized_word in self.blocked_words[user_id]:
            await interaction.response.send_message(
                f"❌ The word '{normalized_word}' is already blocked for {user.display_name}!",
                ephemeral=True
            )
            return
        
        # Add the word
        self.blocked_words[user_id].add(normalized_word)
        await self._save_blocked_words()
        
        await interaction.response.send_message(
            f"✅ Successfully blocked the word '{normalized_word}' for {user.display_name}!",
            ephemeral=True
        )

    @app_commands.command(name="unblockword", description="Remove a blocked word for a specific user")
    @app_commands.describe(
        user="The user to unblock the word for",
        word="The word to unblock"
    )
    async def unblock_word(
        self, 
        interaction: discord.Interaction, 
        user: discord.Member, 
        word: str
    ):
        """Remove a word from the blocked list for a specific user"""
        
        if not self._check_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You need administrator permissions to use this command!",
                ephemeral=True
            )
            return
        
        normalized_word = self._validate_and_normalize_word(word)
        user_id = str(user.id)
        
        # Check if user has blocked words
        if user_id not in self.blocked_words or not self.blocked_words[user_id]:
            await interaction.response.send_message(
                f"❌ No blocked words found for {user.display_name}!",
                ephemeral=True
            )
            return
        
        # Check if word is blocked
        if normalized_word not in self.blocked_words[user_id]:
            await interaction.response.send_message(
                f"❌ The word '{normalized_word}' is not blocked for {user.display_name}!",
                ephemeral=True
            )
            return
        
        # Remove the word
        self.blocked_words[user_id].discard(normalized_word)
        
        # Clean up empty sets
        if not self.blocked_words[user_id]:
            del self.blocked_words[user_id]
            self._users_with_blocks.discard(user_id)
        
        await self._save_blocked_words()
        
        await interaction.response.send_message(
            f"✅ Successfully unblocked the word '{normalized_word}' for {user.display_name}!",
            ephemeral=True
        )

    @app_commands.command(name="listblockedwords", description="List blocked words for a specific user")
    @app_commands.describe(user="The user to list blocked words for")
    async def list_blocked_words(
        self, 
        interaction: discord.Interaction, 
        user: discord.Member
    ):
        """List all blocked words for a specific user"""
        
        if not self._check_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You need administrator permissions to use this command!",
                ephemeral=True
            )
            return
        
        user_id = str(user.id)
        
        # Check if user has blocked words
        if user_id not in self.blocked_words or not self.blocked_words[user_id]:
            await interaction.response.send_message(
                f"📝 No blocked words found for {user.display_name}.",
                ephemeral=True
            )
            return
        
        blocked_words_list = sorted(self.blocked_words[user_id])  # Sort for consistent display
        
        # Handle large lists by truncating if necessary
        max_display = 50
        if len(blocked_words_list) > max_display:
            displayed_words = blocked_words_list[:max_display]
            words_text = ", ".join(f"`{word}`" for word in displayed_words)
            words_text += f"\n... and {len(blocked_words_list) - max_display} more"
        else:
            words_text = ", ".join(f"`{word}`" for word in blocked_words_list)
        
        embed = discord.Embed(
            title=f"🚫 Blocked Words for {user.display_name}",
            description=words_text,
            color=0xFF0000
        )
        embed.set_footer(text=f"Total: {len(blocked_words_list)} word(s)")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearallblockedwords", description="Clear all blocked words for a specific user")
    @app_commands.describe(user="The user to clear all blocked words for")
    async def clear_all_blocked_words(
        self,
        interaction: discord.Interaction,
        user: discord.Member
    ):
        """Clear all blocked words for a specific user"""
        
        if not self._check_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You need administrator permissions to use this command!",
                ephemeral=True
            )
            return
        
        user_id = str(user.id)
        
        if user_id not in self.blocked_words or not self.blocked_words[user_id]:
            await interaction.response.send_message(
                f"❌ No blocked words found for {user.display_name}!",
                ephemeral=True
            )
            return
        
        word_count = len(self.blocked_words[user_id])
        del self.blocked_words[user_id]
        self._users_with_blocks.discard(user_id)
        
        await self._save_blocked_words()
        
        await interaction.response.send_message(
            f"✅ Successfully cleared {word_count} blocked words for {user.display_name}!",
            ephemeral=True
        )

    def _check_admin_permission(self, user: discord.Member) -> bool:
        """Check if user has administrator permission"""
        return user.guild_permissions.administrator

    def _validate_and_normalize_word(self, word: str) -> str:
        """Validate and normalize a word for blocking"""
        if not word or not word.strip():
            return ""
        
        normalized = word.strip().lower()
        
        # Additional validation could be added here
        # e.g., length limits, character restrictions, etc.
        if len(normalized) > 100:  # Reasonable limit
            return ""
        
        return normalized

async def setup(bot):
    await bot.add_cog(WordBlocker(bot))