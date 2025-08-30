# --- plugins/entertainment/word_game_plugin.py ---

import discord
from discord import app_commands
import random
import time
import aiohttp

from plugins.base_plugin import BasePlugin
from shared.utils.decorators import is_bot_admin

class WordGamePlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "word_game"

    def __init__(self, bot):
        super().__init__(bot)
        self.http_session = aiohttp.ClientSession()

    async def cog_unload(self):
        await self.http_session.close()

    async def _is_valid_english_word(self, word: str) -> bool:
        if len(word) < 2: return False
        try:
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
            async with self.http_session.get(url) as resp:
                return resp.status == 200
        except aiohttp.ClientError:
            return False

    async def on_message(self, message: discord.Message) -> bool:
        if not message.guild or not message.content or message.author.bot:
            return False

        gid = message.guild.id
        config = await self.db.get_guild_data(gid, self.name)
        game_channel_id = config.get("game_channel_id")
        game_state = config.get("game_state")

        if not game_channel_id or not game_state or message.channel.id != game_channel_id:
            return False

        word = message.content.strip().lower()
        if not word.isalpha() or len(word.split()) > 1:
            return False

        if not word.startswith(game_state["last_letter"]):
            return False

        if word in game_state.get("used_words", []):
            return False

        if not await self._is_valid_english_word(word):
            # To avoid spamming, let's add a reaction instead of returning False
            await message.add_reaction("❓")
            return True # We've "handled" this invalid attempt

        # --- Word is valid, process score ---
        users_scores = config.setdefault("scores", {})
        user_score = users_scores.setdefault(str(message.author.id), 0)
        users_scores[str(message.author.id)] = user_score + 10

        game_state["last_letter"] = word[-1]
        game_state.setdefault("used_words", []).append(word)

        await self.db.save_guild_data(gid, self.name, config)
        await message.add_reaction("✅")
        await message.channel.send(f"Nice one! The next word must start with **{word[-1].upper()}**.")
        return True

    # --- Commands ---
    game_group = app_commands.Group(name="word-game", description="Commands for the word chain game.")

    @game_group.command(name="start", description="Starts a new game in the configured channel.")
    @is_bot_admin()
    async def start(self, interaction): # <-- Type hint removed
        gid = interaction.guild.id
        config = await self.db.get_guild_data(gid, self.name)
        channel_id = config.get("game_channel_id")
        if not channel_id:
            return await interaction.response.send_message("An admin must set the game channel first with `/word-game set-channel`.", ephemeral=True)

        if interaction.channel.id != channel_id:
            return await interaction.response.send_message(f"This command can only be used in <#{channel_id}>.", ephemeral=True)

        letter = random.choice("abcdefghijklmnopqrstuvwxyz")
        config["game_state"] = {
            "last_letter": letter,
            "used_words": [],
            "timestamp": time.time()
        }
        config["scores"] = {} # Reset scores
        await self.db.save_guild_data(gid, self.name, config)

        await interaction.response.send_message(f"**New Word Game Started!**\nThe first word must start with **{letter.upper()}**.")

    @game_group.command(name="set-channel", description="[Admin] Set the channel for the word game.")
    @app_commands.describe(channel="The channel where the game will be played.")
    @is_bot_admin()
    async def set_channel(self, interaction, channel: discord.TextChannel): # <-- Type hint removed
        gid = interaction.guild.id
        config = await self.db.get_guild_data(gid, self.name)
        config["game_channel_id"] = channel.id
        await self.db.save_guild_data(gid, self.name, config)
        await interaction.response.send_message(f"Word game channel has been set to {channel.mention}.", ephemeral=True)