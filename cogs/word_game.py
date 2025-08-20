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
import aiohttp

from .bot_admin import BotAdmin

# --- Confirmation View for Resetting ---
class ConfirmResetView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.confirmed = None
    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id: await i.response.send_message("This isn't for you.", ephemeral=True); return False
        return True
    @discord.ui.button(label='Confirm Reset', style=discord.ButtonStyle.danger)
    async def confirm(self, i: discord.Interaction, b: discord.ui.Button): self.confirmed = True; await i.response.defer(); self.stop()
    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
    async def cancel(self, i: discord.Interaction, b: discord.ui.Button): self.confirmed = False; await i.response.defer(); self.stop()

class WordGame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # Create a single session for all dictionary API calls
        self.session = aiohttp.ClientSession()

        self.settings_file = Path("data/role_settings.json")
        self.scores_file = Path("data/word_game_scores.json")
        self.game_state_file = Path("data/word_game_state.json")
        
        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        self.scores_data: Dict[str, Dict[str, int]] = self._load_json(self.scores_file)
        self.game_state: Dict[str, Dict] = self._load_json(self.game_state_file) # {"last_letter", "timestamp", "used_words"}

    async def cog_unload(self):
        """Ensure the session is closed when the bot shuts down."""
        await self.session.close()

    def _load_json(self, fp: Path) -> Dict:
        if not fp.exists(): return {}
        try:
            with open(fp, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError): return {}
    async def _save_json(self, data: dict, fp: Path):
        try:
            with open(fp, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except IOError: self.logger.error(f"Error saving {fp}", exc_info=True)
            
    async def check_word_game_message(self, message: discord.Message) -> bool:
        if not message.guild: return False
        gid = str(message.guild.id)
        cid = self.settings_data.get(gid, {}).get("word_game_channel_id")
        if not cid or message.channel.id != cid or gid not in self.game_state: return False
        if message.content.startswith(("/", "!", "?")): return False
        await self._process_game_submission(message)
        return True

    async def _process_game_submission(self, message: discord.Message):
        gid, uid = str(message.guild.id), str(message.author.id)
        state = self.game_state[gid]
        word = message.content.strip().lower()

        if len(word.split()) > 1 or not word.isalpha(): return # Ignore multi-word messages or non-alpha
        
        if word in state.get("used_words", []):
            try: return await message.add_reaction("🔄")
            except discord.Forbidden: return
        
        if not word.startswith(state["last_letter"]):
            try: return await message.add_reaction("❌")
            except discord.Forbidden: return

        async with message.channel.typing():
            is_valid_word = await self._is_valid_english_word(word)
        
        if not is_valid_word:
            try: return await message.add_reaction("❓")
            except discord.Forbidden: return

        # --- Correct Answer ---
        time_taken = time.time() - state["timestamp"]
        xp_gained = self._calculate_xp(time_taken)

        self.scores_data.setdefault(gid, {}).setdefault(uid, 0)
        self.scores_data[gid][uid] += xp_gained
        total_xp = self.scores_data[gid][uid]
        
        state["last_letter"] = word[-1]
        state["timestamp"] = time.time()
        state.setdefault("used_words", []).append(word)

        await self._save_json(self.scores_data, self.scores_file)
        await self._save_json(self.game_state, self.game_state_file)
        
        embed = discord.Embed(
            description=f"**{word.capitalize()}** is a correct answer by {message.author.mention}! (+{xp_gained} XP)",
            color=discord.Color.green()
        )
        await message.reply(embed=embed)
        
        await self._send_new_letter_challenge(message.channel, state["last_letter"])

    # --- Commands ---
    game_group = app_commands.Group(name="word-game", description="Commands for the classic word chain game.")
    
    @game_group.command(name="set-channel", description="Set the channel where the word game will be played.")
    @app_commands.describe(channel="The channel to lock the game to.")
    @BotAdmin.is_bot_admin()
    async def set_channel(self, i: discord.Interaction, channel: discord.TextChannel):
        self.settings_data.setdefault(str(i.guild.id), {})["word_game_channel_id"] = channel.id
        await self._save_json(self.settings_data, self.settings_file)
        await i.response.send_message(f"Okay, the Word Chain game is now locked to {channel.mention}.", ephemeral=True)
        if str(i.guild.id) not in self.game_state:
            await self._send_new_letter_challenge(channel, is_start=True)

    @game_group.command(name="start", description="Starts a new game if one isn't active.")
    async def start(self, i: discord.Interaction):
        gid, cid = str(i.guild.id), self.settings_data.get(str(i.guild.id), {}).get("word_game_channel_id")
        if not cid or i.channel.id != cid: return await i.response.send_message("This can only be used in the game channel.", ephemeral=True)
        if gid in self.game_state: return await i.response.send_message("A game is already active!", ephemeral=True)
        await i.response.send_message("Starting a new round...", ephemeral=True, delete_after=5)
        await self._send_new_letter_challenge(i.channel, is_start=True)
    
    @game_group.command(name="leaderboard", description="Show the word game leaderboard.")
    async def leaderboard(self, i: discord.Interaction, page: app_commands.Range[int, 1, 100] = 1):
        # ... (This command is now fully functional)
        gid = str(i.guild.id); scores = self.scores_data.get(gid, {})
        if not scores: return await i.response.send_message("No scores yet!", ephemeral=True)
        sorted_users = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        embed = discord.Embed(title="🏆 Word Game Leaderboard", color=0xffd700)
        start, end = (page - 1) * 10, page * 10
        lb_text = ""
        for rank, (user_id, xp) in enumerate(sorted_users[start:end], start=start + 1):
            user = self.bot.get_user(int(user_id)); name = user.display_name if user else f"Unknown ({user_id})"
            lb_text += f"**{rank}.** {name} - {xp:,} XP\n"
        embed.description = lb_text or "No scores on this page."; embed.set_footer(text=f"Page {page}/{((len(sorted_users)-1)//10)+1}")
        await i.response.send_message(embed=embed)

    @game_group.command(name="stats", description="Check personal or another user's score and rank.")
    async def stats(self, i: discord.Interaction, user: Optional[discord.Member] = None):
        # ... (This command is now fully functional)
        target = user or i.user
        gid, uid = str(i.guild.id), str(target.id)
        xp = self.scores_data.get(gid, {}).get(uid)
        if xp is None: return await i.response.send_message(f"{target.display_name} hasn't played yet.", ephemeral=True)
        sorted_users = sorted(self.scores_data[gid].items(), key=lambda x: x[1], reverse=True)
        rank = next((r + 1 for r, (user_id, _) in enumerate(sorted_users) if user_id == uid), "N/A")
        embed = discord.Embed(title=f"📊 Stats for {target.display_name}", color=0x00ff00)
        embed.set_thumbnail(url=target.display_avatar.url); embed.add_field(name="Total XP", value=f"{xp:,}", inline=True); embed.add_field(name="Rank", value=f"#{rank}", inline=True)
        await i.response.send_message(embed=embed)
    
    @game_group.command(name="reset", description="[Admin] Reset all scores and used words for the word game.")
    @BotAdmin.is_bot_admin()
    async def reset(self, i: discord.Interaction):
        # ... (This command is now fully functional)
        view = ConfirmResetView(i.user.id)
        await i.response.send_message("⚠️ **Are you sure?** This will wipe all scores and used words.", view=view, ephemeral=True)
        await view.wait()
        if view.confirmed:
            gid = str(i.guild.id)
            self.scores_data[gid] = {}; self.game_state.pop(gid, None)
            await self._save_json(self.scores_data, self.scores_file); await self._save_json(self.game_state, self.game_state_file)
            await i.edit_original_response(content="✅ Game data has been reset.", view=None)
        else: await i.edit_original_response(content="❌ Reset cancelled.", view=None)

    # --- Helpers ---
    async def _is_valid_english_word(self, word: str) -> bool:
        """Checks if a word is a valid English word using a free dictionary API."""
        if len(word) < 2: return False # Single-letter words are boring
        try:
            async with self.session.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}") as resp:
                # The API returns 200 for a valid word, and 404 for an invalid one.
                return resp.status == 200
        except aiohttp.ClientError:
            self.logger.warning(f"Dictionary API call failed for word: {word}")
            return False # Fail safe if the API is down

    def _get_random_letter(self) -> str: return random.choice("abcdefghijklmnopqrstuvwxyz")
    
    async def _send_new_letter_challenge(self, channel: discord.TextChannel, letter: Optional[str] = None, is_start: bool = False):
        gid = str(channel.guild.id)
        if is_start:
            letter = self._get_random_letter()
            self.game_state[gid] = {"last_letter": letter, "timestamp": time.time(), "used_words": []}
            await self._save_json(self.game_state, self.game_state_file)
            message = f"A new Word Chain game has started! The first word must start with **{letter.upper()}**."
        else:
            message = f"The next word must start with **{letter.upper()}**."

        embed = discord.Embed(description=message, color=0x00aaff)
        await channel.send(embed=embed)
        
    def _calculate_xp(self, time_taken: float) -> int:
        # Using more reasonable XP values for a faster-paced game
        if time_taken <= 10: return 100
        elif time_taken <= 30: return 50
        elif time_taken <= 60: return 25
        else: return 10
        
async def setup(bot):
    await bot.add_cog(WordGame(bot))