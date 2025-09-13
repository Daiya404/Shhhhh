# cogs/moderation/word_blocker.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import time
from typing import Optional

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

class WordBlocker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["word_blocker"]
        self.data_manager = self.bot.data_manager
        self.COOLDOWN_SECONDS = 5
        self.channel_cooldowns = {}
        self.blocklist_cache = {}
        self.regex_cache = {}

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info("Loading word blocklist into memory and building regex cache...")
        self.blocklist_cache = await self.data_manager.get_data("word_blocklist")
        for guild_id, data in self.blocklist_cache.items():
            self._update_regex_for_guild(guild_id, data)
        self.logger.info("Word Blocker cache is ready.")

    def _compile_word_list(self, words: list) -> re.Pattern | None:
        if not words: return None
        pattern = r'\b(' + '|'.join(re.escape(word) for word in words) + r')\b'
        return re.compile(pattern, re.IGNORECASE)

    def _update_regex_for_guild(self, guild_id: str, guild_data: dict):
        self.regex_cache[guild_id] = {
            "global": self._compile_word_list(guild_data.get("global", [])),
            "users": { user_id: self._compile_word_list(words) for user_id, words in guild_data.get("users", {}).items() }
        }

    async def check_and_handle_message(self, message: discord.Message) -> bool:
        if not message.guild: return False
        guild_id, user_id = str(message.guild.id), str(message.author.id)
        guild_cache = self.regex_cache.get(guild_id)
        if not guild_cache: return False
        triggered_word = None
        global_regex = guild_cache.get("global")
        if global_regex and (match := global_regex.search(message.content)):
            triggered_word = match.group(1)
        if not triggered_word and (user_regex := guild_cache.get("users", {}).get(user_id)):
            if match := user_regex.search(message.content):
                triggered_word = match.group(1)
        if triggered_word:
            await self._handle_blocked_message(message, triggered_word)
            return True
        return False

    async def _handle_blocked_message(self, message: discord.Message, trigger_word: str):
        try:
            await message.delete()
            now = time.time()
            channel_id = message.channel.id
            last_warning_time = self.channel_cooldowns.get(channel_id, 0)
            if now - last_warning_time < self.COOLDOWN_SECONDS:
                return
            self.channel_cooldowns[channel_id] = now
            warning_text = f"{message.author.mention}, your message was removed because it contained a blocked term (`{trigger_word}`). Watch it."
            await message.channel.send(warning_text, delete_after=12)
        except (discord.Forbidden, discord.NotFound):
            self.logger.warning(f"Failed to delete a blocked message in {message.channel.name}.")

    # --- Admin-Only Command to Add/Remove Words ---
    @app_commands.command(name="blockword", description="Add or remove words from the blocklist.")
    @app_commands.default_permissions(administrator=True) # Visible only to admins
    @is_bot_admin()
    @app_commands.describe(scope="Modify the 'global' or a 'user' list.", action="'add' or 'remove' words.", words="The word(s) to modify, separated by spaces.", user="The user to modify (if scope is 'user').")
    @app_commands.choices(scope=[app_commands.Choice(name="Global", value="global"), app_commands.Choice(name="User", value="user")], action=[app_commands.Choice(name="Add", value="add"), app_commands.Choice(name="Remove", value="remove")])
    async def manage_blockword(self, interaction: discord.Interaction, scope: str, action: str, words: str, user: Optional[discord.Member] = None):
        await interaction.response.defer()
        if scope == "user" and not user:
            return await interaction.followup.send("You must specify a user for the 'user' scope.", ephemeral=True)
        words_to_modify = {word.lower().strip() for word in words.split()}
        if not words_to_modify:
            return await interaction.followup.send("You have to provide words to modify.", ephemeral=True)
        guild_id = str(interaction.guild.id)
        guild_blocklist = self.blocklist_cache.setdefault(guild_id, {"global": [], "users": {}})
        target_list_owner = guild_blocklist if scope == "global" else guild_blocklist.setdefault("users", {})
        target_key = "global" if scope == "global" else str(user.id)
        word_list = target_list_owner.setdefault(target_key, [])
        word_set = set(word_list)
        changed_words = words_to_modify.intersection(word_set) if action == "remove" else words_to_modify.difference(word_set)
        if not changed_words:
            error_msg = self.personality["not_blocked"] if action == "remove" else self.personality["already_blocked"]
            return await interaction.followup.send(error_msg, ephemeral=True)
        if action == "add":
            word_set.update(changed_words)
            response_template = self.personality["word_added"]
        else:
            word_set.difference_update(changed_words)
            response_template = self.personality["word_removed"]
        target_list_owner[target_key] = sorted(list(word_set))
        await self.data_manager.save_data("word_blocklist", self.blocklist_cache)
        self._update_regex_for_guild(guild_id, guild_blocklist)
        user_prefix = f"For **{user.display_name}**: " if user else ""
        await interaction.followup.send(f"{user_prefix}{response_template} Words: `{'`, `'.join(sorted(changed_words))}`")

    # --- Public Command to List Words ---
    @app_commands.command(name="blockword-list", description="List globally or user-specifically blocked words.")
    # REMOVED: @app_commands.default_permissions(administrator=True)
    # REMOVED: @BotAdmin.is_bot_admin()
    @app_commands.describe(user="The user whose list you want to see (optional).")
    async def list_blockwords(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        # List is sensitive, so it's always ephemeral (private).
        await interaction.response.defer(ephemeral=True)

        guild_blocklist = self.blocklist_cache.get(str(interaction.guild.id), {})

        # --- PERMISSION CHECK: Only admins can view other users' lists ---
        # A regular user can only view the global list or their own list.
        if user and user.id != interaction.user.id:
            # Manually check for admin permissions here.
            admin_cog = self.bot.get_cog("BotAdmin")
            if not admin_cog or not await admin_cog.is_bot_admin().predicate(interaction):
                return await interaction.followup.send("You can only view the global blocklist or your own. Don't be nosy.")

        target_user = user or interaction.user
        
        if user: # List a specific user's blocked words
            words = guild_blocklist.get("users", {}).get(str(target_user.id), [])
            if not words:
                return await interaction.followup.send(self.personality["user_list_empty"].format(user=target_user.display_name))
            embed = discord.Embed(title=f"Blocked Words for {target_user.display_name}", description=", ".join(f"`{w}`" for w in words), color=discord.Color.orange())
        else: # List the global blocked words
            words = guild_blocklist.get("global", [])
            if not words:
                return await interaction.followup.send(self.personality["list_empty"])
            embed = discord.Embed(title="Globally Blocked Words", description=", ".join(f"`{w}`" for w in words), color=discord.Color.red())
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(WordBlocker(bot))