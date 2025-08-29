# --- plugins/user/progression_plugin.py ---

import discord
from discord import app_commands
import random
import time
from typing import Dict

from plugins.base_plugin import BasePlugin
from shared.utils.image_gen import ImageGenerator
import aiohttp # Add this import

class ProgressionPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "progression"

    def __init__(self, bot):
        super().__init__(bot)
        # Each plugin that needs to make web requests gets its own session
        self.http_session = aiohttp.ClientSession()
        self.image_gen = ImageGenerator(self.http_session)
        self.cooldowns: Dict[int, Dict[int, float]] = {}

    # This is a special method `discord.py` calls when a cog is unloaded
    async def cog_unload(self):
        # Ensure the session is closed when the plugin is unloaded
        await self.http_session.close()

    # --- XP Calculation Logic ---
    def _xp_for_level(self, level: int) -> int:
        return 5 * (level ** 2) + 50 * level + 100

    def _level_for_xp(self, xp: int) -> int:
        if xp < 100: return 0
        level = 0
        while self._xp_for_level(level + 1) <= xp:
            level += 1
        return level

    # --- Event Handler for Messages ---
    async def on_message(self, message: discord.Message) -> bool:
        if not message.guild or message.author.bot:
            return False # Don't handle, continue to other plugins

        # Simplified XP gain logic
        gid, uid = message.guild.id, message.author.id
        now = time.time()
        self.cooldowns.setdefault(gid, {})
        if (now - self.cooldowns[gid].get(uid, 0)) < 60: # 60s cooldown
            return False

        self.cooldowns[gid][uid] = now
        xp_gain = random.randint(15, 25)

        # Get all guild data for this plugin
        guild_data = await self.db.get_guild_data(gid, self.name)
        users_data = guild_data.setdefault("users", {})
        user_data = users_data.setdefault(str(uid), {"xp": 0})
        
        old_level = self._level_for_xp(user_data["xp"])
        user_data["xp"] += xp_gain
        new_level = self._level_for_xp(user_data["xp"])

        if new_level > old_level:
            # We would handle level up announcements and role rewards here
            self.logger.info(f"{message.author.display_name} leveled up to {new_level} in {message.guild.name}")
            # In a real implementation, you'd add a level up message here.

        await self.db.save_guild_data(gid, self.name, guild_data)
        return False # We processed XP, but don't stop other plugins

    # --- Unified Rank/Profile Command ---
    @app_commands.command(name="rank", description="Check your or another user's level and rank.")
    @app_commands.describe(user="The user to check the rank of.")
    async def rank(self, interaction: discord.Interaction, user: discord.Member = None):
        await interaction.response.defer()
        target = user or interaction.user
        gid, uid = str(interaction.guild.id), str(target.id)

        guild_data = await self.db.get_guild_data(interaction.guild_id, self.name)
        users_data = guild_data.get("users", {})

        if not users_data or uid not in users_data:
            return await interaction.followup.send(f"{target.display_name} hasn't earned any XP yet.")

        # Calculate rank
        sorted_users = sorted(users_data.items(), key=lambda item: item[1].get('xp', 0), reverse=True)
        rank = next((i + 1 for i, (user_id, _) in enumerate(sorted_users) if user_id == uid), 0)

        # Prepare data for the card
        user_data = users_data[uid]
        level = self._level_for_xp(user_data.get('xp', 0))
        xp_for_current = self._xp_for_level(level)
        xp_for_next = self._xp_for_level(level + 1)
        
        card_data = {
            "rank": rank,
            "level": level,
            "current_xp": user_data.get('xp', 0) - xp_for_current,
            "needed_xp": xp_for_next - xp_for_current,
            "bio": user_data.get("profile", {}).get("bio", "No bio set."),
            "background_url": user_data.get("card", {}).get("background_url"),
            "color": user_data.get("card", {}).get("color", "#FFFFFF"),
        }

        try:
            image_bytes = await self.image_gen.create_user_card(target, card_data)
            file = discord.File(fp=image_bytes, filename=f"rank_{target.id}.png")
            await interaction.followup.send(file=file)
        except Exception as e:
            self.logger.error("Failed to generate rank card", exc_info=e)
            await interaction.followup.send("Sorry, I had trouble creating the rank card.", ephemeral=True)

    # --- Profile Customization ---
    profile_group = app_commands.Group(name="profile", description="Set your personal profile information.")
    
    @profile_group.command(name="set-bio", description="Set your short bio for your rank card.")
    @app_commands.describe(text="Your bio (max 100 characters).")
    async def set_bio(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 100]):
        gid, uid = interaction.guild_id, str(interaction.user.id)
        guild_data = await self.db.get_guild_data(gid, self.name)

        # Create nested dictionaries safely
        users_data = guild_data.setdefault("users", {})
        user_data = users_data.setdefault(uid, {})
        profile_data = user_data.setdefault("profile", {})
        profile_data["bio"] = text

        await self.db.save_guild_data(gid, self.name, guild_data)
        await interaction.response.send_message("Fine, I've updated your bio.", ephemeral=True)