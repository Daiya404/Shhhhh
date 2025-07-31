import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
from typing import Dict

from .bot_admin import BotAdmin

PERSONALITY = {
    "detention_start": "Done. {user} has been placed in detention. Let's see if they learn their lesson.",
    "detention_progress": "Keep going, {user}. `{remaining}` more times. Don't mess it up.",
    "detention_done": "Hmph. You finished. I've restored your roles. Try to be less of a problem from now on.",
    "missing_role": "I can't do my job if you haven't done yours. A role named `BEHAVE` needs to exist first.",
    "cant_manage": "I can't manage `{user}`. Their role is higher than mine. That's a 'you' problem, not a 'me' problem.",
    "already_detained": "That user is already in detention. Don't waste my time."
}


class Detention(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.data_dir = Path("data")
        self.detention_file = self.data_dir / "detention_data.json"
        self.detention_data: Dict[str, dict] = self._load_json()

    async def is_user_detained(self, message: discord.Message) -> bool:
        """Checks if a user is in detention. Safe to call from anywhere."""
        if not message.guild: return False
        guild_id_str = str(message.guild.id)
        user_id_str = str(message.author.id)
        return guild_id_str in self.detention_data and user_id_str in self.detention_data[guild_id_str]

    async def handle_detention_message(self, message: discord.Message):
        """The logic for handling a message from a detained user."""
        guild_id_str = str(message.guild.id)
        user_id_str = str(message.author.id)
        data = self.detention_data[guild_id_str][user_id_str]
        
        if message.channel.id != data["channel_id"]:
            try: await message.delete()
            except discord.NotFound: pass
            return

        if message.content.strip() == data["sentence"]:
            data["reps_remaining"] -= 1
            await self._save_json()
            if data["reps_remaining"] <= 0:
                await self._release_from_detention(message.guild, message.author)
            else:
                progress_msg = PERSONALITY["detention_progress"].format(user=message.author.mention, remaining=data['reps_remaining'])
                try: await message.reply(progress_msg, delete_after=8, mention_author=False)
                except discord.HTTPException: pass
        else:
            try: await message.delete()
            except discord.NotFound: pass

    def _load_json(self) -> dict:
        if not self.detention_file.exists(): return {}
        try:
            with open(self.detention_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Error loading {self.detention_file}: {e}")
            return {}

    async def _save_json(self):
        try:
            with open(self.detention_file, 'w', encoding='utf-8') as f:
                json.dump(self.detention_data, f, indent=2)
        except IOError as e:
            self.logger.error(f"Error saving {self.detention_file}: {e}")
            
    detention_group = app_commands.Group(name="detention", description="Commands for managing the user detention system.")

    @detention_group.command(name="start", description="Put a user in detention, forcing them to type a sentence.")
    @app_commands.describe(user="The user to put in detention.", sentence="The sentence they must type repeatedly.", repetitions="How many times they must type it (1-100).")
    @BotAdmin.is_bot_admin()
    async def start_detention(self, interaction: discord.Interaction, user: discord.Member, sentence: str, repetitions: app_commands.Range[int, 1, 100]):
        guild = interaction.guild
        guild_id_str = str(guild.id)
        user_id_str = str(user.id)
        if guild_id_str in self.detention_data and user_id_str in self.detention_data[guild_id_str]:
            await interaction.response.send_message(PERSONALITY["already_detained"], ephemeral=True)
            return
        detention_role = discord.utils.get(guild.roles, name="BEHAVE")
        if not detention_role:
            await interaction.response.send_message(PERSONALITY["missing_role"], ephemeral=True)
            return
        original_roles = [role.id for role in user.roles if not role.is_default()]
        try:
            await user.edit(roles=[detention_role], reason=f"Detention by {interaction.user.display_name}")
        except discord.Forbidden:
            await interaction.response.send_message(PERSONALITY["cant_manage"].format(user=user.display_name), ephemeral=True)
            return
        if guild_id_str not in self.detention_data:
            self.detention_data[guild_id_str] = {}
        self.detention_data[guild_id_str][user_id_str] = {
            "sentence": sentence,
            "reps_remaining": repetitions,
            "original_roles": original_roles,
            "channel_id": interaction.channel.id
        }
        await self._save_json()
        await interaction.response.send_message(PERSONALITY["detention_start"].format(user=user.mention))
        
    async def _release_from_detention(self, guild: discord.Guild, user: discord.Member):
        guild_id_str = str(guild.id)
        user_id_str = str(user.id)
        if guild_id_str not in self.detention_data or user_id_str not in self.detention_data[guild_id_str]: return
        data = self.detention_data[guild_id_str].pop(user_id_str)
        if not self.detention_data[guild_id_str]: del self.detention_data[guild_id_str]
        original_role_ids = data.get("original_roles", [])
        roles_to_restore = [guild.get_role(role_id) for role_id in original_role_ids if guild.get_role(role_id) is not None]
        try:
            await user.edit(roles=roles_to_restore, reason="Released from detention.")
        except discord.Forbidden:
            self.logger.error(f"Failed to restore roles for {user.display_name} in {guild.name}.")
        await self._save_json()
        channel = guild.get_channel(data["channel_id"])
        if channel:
            await channel.send(PERSONALITY["detention_done"].format(user=user.mention))


async def setup(bot):
    await bot.add_cog(Detention(bot))