# cogs/fun/word_game.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import random
import time
import asyncio
import aiofiles 
import re # Import the regular expression module
from collections import defaultdict
from typing import Dict, Optional, Set, List

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

# --- CORRECTED MODAL ---
class SetChannelModal(discord.ui.Modal, title='Set Word Game Channel'):
    channel_input = discord.ui.TextInput(
        label='Channel',
        placeholder='Paste the channel ID or mention the channel (#channel)',
        style=discord.TextStyle.short
    )

    def __init__(self, game_cog: 'WordGame'):
        super().__init__(timeout=180)
        self.game_cog = game_cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Defer in case channel lookup is slow
        channel_str = self.channel_input.value.strip()
        channel: Optional[discord.TextChannel] = None

        # --- FIX: Manually parse the channel ID instead of using the broken converter ---
        # The old converter caused an AttributeError because it's not compatible with Interactions.
        
        # Check for a channel mention first, e.g., <#123456789012345678>
        match = re.match(r'<#(\d+)>$', channel_str)
        if match:
            channel_id = int(match.group(1))
            channel = interaction.guild.get_channel(channel_id)
        # If not a mention, check if it's a raw ID
        elif channel_str.isdigit():
            channel_id = int(channel_str)
            channel = interaction.guild.get_channel(channel_id)

        if not channel or not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("I couldn't find that text channel. Please provide a valid channel mention or ID.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        self.game_cog.settings_cache.setdefault(guild_id, {})["word_game_channel_id"] = channel.id
        await self.game_cog.data_manager.save_data("role_settings", self.game_cog.settings_cache)
        
        await interaction.followup.send(self.game_cog.personality["channel_set"].format(channel=channel.mention), ephemeral=True)
        if guild_id not in self.game_cog.game_state_cache:
            await self.game_cog._send_new_letter_challenge(channel, is_start=True)

# --- The rest of your file is largely the same, but I've ensured it uses the corrected modal ---
# ... (WordGameAdminView, ConfirmResetView, and the main WordGame cog class follow) ...
# I will include the full file for completeness.

class WordGameAdminView(discord.ui.View):
    def __init__(self, game_cog: 'WordGame', author_id: int):
        super().__init__(timeout=180)
        self.game_cog = game_cog
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Set Channel', style=discord.ButtonStyle.primary, emoji='🔧')
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Now uses the corrected modal
        modal = SetChannelModal(self.game_cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label='Start New Game', style=discord.ButtonStyle.success, emoji='🚀')
    async def start_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild.id)
        game_channel_id = self.game_cog.settings_cache.get(guild_id, {}).get("word_game_channel_id")
        if not game_channel_id:
            await interaction.followup.send("The game channel must be set first.", ephemeral=True)
            return
        game_channel = self.game_cog.bot.get_channel(game_channel_id)
        await self.game_cog._send_new_letter_challenge(game_channel, is_start=True)
        await interaction.followup.send("A new game has been started in the channel.", ephemeral=True)

    @discord.ui.button(label='Reset All Data', style=discord.ButtonStyle.danger, emoji='🗑️')
    async def reset_data(self, interaction: discord.Interaction, button: discord.ui.Button):
        confirm_view = ConfirmResetView(self.author_id)
        await interaction.response.send_message(self.game_cog.personality["reset_confirm"], view=confirm_view, ephemeral=True)
        await confirm_view.wait()

        if confirm_view.confirmed:
            guild_id = str(interaction.guild.id)
            self.game_cog.scores_cache.pop(guild_id, None)
            self.game_cog.game_state_cache.pop(guild_id, None)
            await self.game_cog._save_game_state()
            await interaction.edit_original_response(content=self.game_cog.personality["reset_success"], view=None)
        else:
            await interaction.edit_original_response(content=self.game_cog.personality["reset_cancel"], view=None)

class ConfirmResetView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.confirmed: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Confirm Reset', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

class WordGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["word_game"]
        self.data_manager = self.bot.data_manager
        self.settings_cache: Dict[str, Dict] = {}
        self.scores_cache: Dict[str, Dict[str, int]] = {}
        self.game_state_cache: Dict[str, Dict] = {}
        self.word_list: Set[str] = set()
        self._guild_locks = defaultdict(asyncio.Lock)
        self.stale_game_task.start()

    async def _is_user_bot_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator: return True
        cog = self.bot.get_cog('BotAdmin')
        if not cog: return False
        bot_admins_data = await cog.data_manager.get_data("bot_admins")
        guild_admins = bot_admins_data.get(str(interaction.guild.id), [])
        return interaction.user.id in guild_admins

    # ... (cog_load and other methods remain the same) ...
    async def cog_load(self):
        self.logger.info("Loading WordGame data and dictionary into memory...")
        dictionary_path = self.bot.settings.ASSETS_DIR / "dictionary.txt"
        try:
            async with aiofiles.open(dictionary_path, "r", encoding="utf-8") as f: self.word_list = {line.strip().lower() for line in await f.readlines()}
            self.logger.info(f"Successfully loaded {len(self.word_list):,} words.")
        except FileNotFoundError:
            self.logger.error(f"CRITICAL: {dictionary_path} not found! WordGame is disabled."); self.word_list = set()
        self.settings_cache = await self.data_manager.get_data("role_settings")
        self.scores_cache = await self.data_manager.get_data("word_game_scores")
        game_state_data = await self.data_manager.get_data("word_game_state")
        for guild_id, state in game_state_data.items():
            if "used_words" in state and isinstance(state["used_words"], list): state["used_words"] = set(state["used_words"])
        self.game_state_cache = game_state_data; self.logger.info("WordGame data cache is ready.")

    def cog_unload(self): self.stale_game_task.cancel()

    @tasks.loop(minutes=5)
    async def stale_game_task(self):
        now = time.time()
        for guild_id_str, state in list(self.game_state_cache.items()):
            if now - state.get("timestamp", 0) > 43200:
                channel_id = self.settings_cache.get(guild_id_str, {}).get("word_game_channel_id")
                if channel_id and (channel := self.bot.get_channel(int(channel_id))):
                    self.logger.info(f"Stale WordGame round in guild {guild_id_str}. Resetting.")
                    await channel.send("This round has been idle for a while... Let's start fresh!")
                    await self._send_new_letter_challenge(channel, is_start=True)
    
    @stale_game_task.before_loop
    async def before_stale_game_task(self): await self.bot.wait_until_ready()

    async def _save_game_state(self):
        state_to_save = {}
        for guild_id, state in self.game_state_cache.items():
            state_copy = state.copy()
            if "used_words" in state_copy: state_copy["used_words"] = list(state_copy["used_words"])
            state_to_save[guild_id] = state_copy
        await self.data_manager.save_data("word_game_scores", self.scores_cache)
        await self.data_manager.save_data("word_game_state", state_to_save)

    async def check_word_game_message(self, message: discord.Message) -> bool:
        if not message.guild or message.author.bot: return False
        guild_id_str = str(message.guild.id)
        channel_id = self.settings_cache.get(guild_id_str, {}).get("word_game_channel_id")
        if not channel_id or message.channel.id != channel_id or guild_id_str not in self.game_state_cache: return False
        if message.content.startswith(tuple(self.bot.command_prefix)) or message.content.startswith("/"): return False
        async with self._guild_locks[message.guild.id]: await self._process_game_submission(message)
        return True

    async def _process_game_submission(self, message: discord.Message):
        guild_id, user_id = str(message.guild.id), str(message.author.id)
        state = self.game_state_cache[guild_id]; word = message.content.strip().lower()
        if len(word.split()) > 1 or not word.isalpha(): return
        if word in state.get("used_words", set()): return await message.add_reaction("🔄")
        if not word.startswith(state["last_letter"]): return await message.add_reaction("❌")
        if not self._is_valid_english_word(word): return await message.add_reaction("❓")
        time_taken = time.time() - state["timestamp"]; xp_gained = self._calculate_xp(time_taken)
        guild_scores = self.scores_cache.setdefault(guild_id, {}); guild_scores[user_id] = guild_scores.get(user_id, 0) + xp_gained
        state["last_letter"] = word[-1]; state.setdefault("used_words", set()).add(word); state["timestamp"] = time.time()
        await self._save_game_state()
        correct_embed = discord.Embed(title="✅ Correct!", description=f"**`{word.capitalize()}`** by {message.author.mention}", color=discord.Color.green())
        correct_embed.add_field(name="XP Gained", value=f"+{xp_gained}"); correct_embed.add_field(name="Total XP", value=f"{guild_scores[user_id]:,}")
        challenge_embed = discord.Embed(title="Next Word Challenge!", description=f"The next word must start with **{state['last_letter'].upper()}**!", color=0x00aaff)
        await message.reply(embeds=[correct_embed, challenge_embed], mention_author=False)

    @app_commands.command(name="wordgame-admin", description="[Admin] Configure the word chain game.")
    @app_commands.default_permissions(administrator=True)
    async def wordgame_admin(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self._is_user_bot_admin(interaction):
            await interaction.followup.send(self.personality["no_perm_check"], ephemeral=True)
            return
        embed = discord.Embed(title="Word Game Admin Panel", description="Please select an action to perform.", color=discord.Color.blue())
        view = WordGameAdminView(self, interaction.user.id); await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="wordgame-stats", description="Show the word game leaderboard or a user's stats.")
    @app_commands.describe(user="The user whose stats you want to see (optional).")
    async def wordgame_stats(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True) # Defer early
        guild_id, target_user = str(interaction.guild.id), user or interaction.user
        guild_scores = self.scores_cache.get(guild_id, {})
        if not guild_scores: return await interaction.followup.send(self.personality["no_scores"])
        if user:
            xp = guild_scores.get(str(target_user.id))
            if xp is None: return await interaction.followup.send(f"{target_user.display_name} hasn't played yet.")
            sorted_users = sorted(guild_scores.items(), key=lambda x: x[1], reverse=True)
            try: rank = [i for i, (uid, _) in enumerate(sorted_users, 1) if uid == str(target_user.id)][0]
            except IndexError: rank = "N/A"
            embed = discord.Embed(title=f"📊 Stats for {target_user.display_name}", color=discord.Color.green())
            embed.set_thumbnail(url=target_user.display_avatar.url); embed.add_field(name="Total XP", value=f"{xp:,}"); embed.add_field(name="Rank", value=f"#{rank}")
            await interaction.followup.send(embed=embed)
        else:
            sorted_users = sorted(guild_scores.items(), key=lambda x: x[1], reverse=True)
            embed = discord.Embed(title="🏆 Word Game Leaderboard", color=0xffd700)
            description = [f"**{rank}.** {interaction.guild.get_member(int(user_id)).display_name if interaction.guild.get_member(int(user_id)) else f'User ({user_id})'} - **{xp:,}** XP" for rank, (user_id, xp) in enumerate(sorted_users[:10], 1)]
            embed.description = "\n".join(description)
            await interaction.followup.send(embed=embed)

    def _is_valid_english_word(self, word: str) -> bool: return len(word) >= 2 and word in self.word_list
        
    async def _send_new_letter_challenge(self, channel: discord.TextChannel, is_start: bool = False):
        guild_id = str(channel.guild.id); letter = random.choice("abcdefghijklmnopqrstuvwxyz")
        self.game_state_cache[guild_id] = {"last_letter": letter, "timestamp": time.time(), "used_words": set()}
        await self._save_game_state()
        embed = discord.Embed(title="🚀 New Word Chain Game Started!", description=f"The first word must start with **{letter.upper()}**!", color=0x5865F2)
        if not is_start: embed.title = "New Round!"
        await channel.send(embed=embed)

    def _calculate_xp(self, time_taken: float) -> int:
        if time_taken <= 10: return 100
        elif time_taken <= 30: return 50
        elif time_taken <= 60: return 25
        else: return 10

async def setup(bot):
    await bot.add_cog(WordGame(bot))