import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
import re
from typing import Dict, List

from .bot_admin import BotAdmin

# --- Personality Responses for this Cog ---
PERSONALITY = {
    "trigger_set": "Fine. If anyone says `{trigger}`, I'll reply with that. I hope it's not something stupid.",
    "alt_added": "Another one? Okay, I've added `{alternative}` as an alternative for `{trigger}`.",
    "trigger_removed": "Noted. I'll no longer reply to `{trigger}`.",
    "trigger_not_found": "I can't find a trigger with that name. Try checking the list.",
    "already_exists": "That trigger or alternative already exists. Pay attention.",
    "list_empty": "There are no auto-replies set up for this server.",
    "error_empty": "You can't set an empty trigger or alternative. Obviously."
}

class AutoReply(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.replies_file = Path("data/auto_replies.json")
        
        # Data: {guild_id: {trigger_word: {"reply": "...", "alts": [...]}}}
        self.reply_data: Dict[str, Dict] = self._load_json()
        
        # Cache for compiled regex patterns for maximum efficiency
        self.regex_cache: Dict[str, re.Pattern] = {}
        self._build_all_regex_caches()

    # --- Data & Cache ---
    def _load_json(self) -> Dict:
        if not self.replies_file.exists(): return {}
        try:
            with open(self.replies_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            self.logger.error(f"Error loading {self.replies_file}", exc_info=True)
            return {}

    async def _save_json(self):
        try:
            with open(self.replies_file, 'w', encoding='utf-8') as f:
                json.dump(self.reply_data, f, indent=2, ensure_ascii=False)
        except IOError:
            self.logger.error(f"Error saving {self.replies_file}", exc_info=True)
            
    def _build_all_regex_caches(self):
        for guild_id, triggers in self.reply_data.items():
            self._update_regex_for_guild(guild_id)

    def _update_regex_for_guild(self, guild_id: str):
        all_triggers = []
        guild_triggers = self.reply_data.get(guild_id, {})
        for trigger, data in guild_triggers.items():
            all_triggers.append(trigger)
            all_triggers.extend(data.get("alts", []))
        
        if not all_triggers:
            self.regex_cache[guild_id] = None
            return
            
        pattern = r'\b(' + '|'.join(re.escape(word) for word in all_triggers) + r')\b'
        self.regex_cache[guild_id] = re.compile(pattern, re.IGNORECASE)

    # --- Core Logic for Traffic Cop ---
    async def check_for_reply(self, message: discord.Message) -> bool:
        """Checks for a trigger and sends a reply. Returns True if handled."""
        if not message.guild: return False

        guild_id = str(message.guild.id)
        guild_regex = self.regex_cache.get(guild_id)
        if not guild_regex: return False

        match = guild_regex.search(message.content)
        if not match: return False
        
        triggered_word = match.group(1).lower()
        guild_triggers = self.reply_data.get(guild_id, {})
        reply_content = None

        for main_trigger, data in guild_triggers.items():
            if triggered_word == main_trigger or triggered_word in data.get("alts", []):
                reply_content = data["reply"]
                break
        
        if reply_content:
            await self._send_reply(message, reply_content)
            return True
        return False

    async def _send_reply(self, message: discord.Message, reply: str):
        """
        Sends the reply. For this feature, we just send the raw text/URL.
        Discord will automatically render the image preview.
        """
        try:
            await message.reply(reply, mention_author=False)
        except discord.Forbidden:
            self.logger.warning(f"Missing permissions to send auto-reply in {message.channel.name}.")
        except Exception as e:
            self.logger.error(f"Failed to send auto-reply: {e}", exc_info=True)

    # --- Command Group ---
    nga_group = app_commands.Group(name="nga", description="Manage automatic replies to trigger words.")

    @nga_group.command(name="add", description="Set up a new trigger word with a custom reply.")
    @app_commands.describe(trigger="The word/phrase to listen for.", reply="The reply (text or image/GIF URL).")
    @BotAdmin.is_bot_admin()
    async def add(self, interaction: discord.Interaction, trigger: str, reply: str):
        guild_id = str(interaction.guild_id)
        trigger_key = trigger.lower().strip()
        if not trigger_key or not reply.strip():
            return await interaction.response.send_message(PERSONALITY["error_empty"], ephemeral=True)
            
        self.reply_data.setdefault(guild_id, {})
        if trigger_key in self.reply_data[guild_id]:
            return await interaction.response.send_message(PERSONALITY["already_exists"], ephemeral=True)

        self.reply_data[guild_id][trigger_key] = {"reply": reply, "alts": []}
        await self._save_json()
        self._update_regex_for_guild(guild_id)
        
        await interaction.response.send_message(PERSONALITY["trigger_set"].format(trigger=trigger), ephemeral=True)

    @nga_group.command(name="add-alt", description="Add an alternative word to an existing trigger.")
    @app_commands.describe(main_trigger="The trigger to add an alternative for.", alternative="The new alternative word.")
    @BotAdmin.is_bot_admin()
    async def add_alt(self, interaction: discord.Interaction, main_trigger: str, alternative: str):
        guild_id = str(interaction.guild_id)
        main_key = main_trigger.lower().strip()
        alt_key = alternative.lower().strip()
        if not main_key or not alt_key:
            return await interaction.response.send_message(PERSONALITY["error_empty"], ephemeral=True)
        
        guild_triggers = self.reply_data.get(guild_id, {})
        if main_key not in guild_triggers:
            return await interaction.response.send_message(PERSONALITY["trigger_not_found"], ephemeral=True)
        
        if alt_key in guild_triggers[main_key].get("alts", []) or alt_key == main_key:
            return await interaction.response.send_message(PERSONALITY["already_exists"], ephemeral=True)
            
        guild_triggers[main_key].setdefault("alts", []).append(alt_key)
        await self._save_json()
        self._update_regex_for_guild(guild_id)

        await interaction.response.send_message(PERSONALITY["alt_added"].format(alternative=alternative, trigger=main_trigger), ephemeral=True)

    @nga_group.command(name="remove", description="Remove a trigger and all its alternatives.")
    @app_commands.describe(trigger="The main trigger word to remove.")
    @BotAdmin.is_bot_admin()
    async def remove(self, interaction: discord.Interaction, trigger: str):
        guild_id = str(interaction.guild_id)
        trigger_key = trigger.lower().strip()

        if guild_id not in self.reply_data or trigger_key not in self.reply_data[guild_id]:
            return await interaction.response.send_message(PERSONALITY["trigger_not_found"], ephemeral=True)

        del self.reply_data[guild_id][trigger_key]
        await self._save_json()
        self._update_regex_for_guild(guild_id)

        await interaction.response.send_message(PERSONALITY["trigger_removed"].format(trigger=trigger), ephemeral=True)

    @nga_group.command(name="list", description="List all configured auto-replies for this server.")
    async def list(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        guild_triggers = self.reply_data.get(guild_id, {})
        if not guild_triggers:
            return await interaction.response.send_message(PERSONALITY["list_empty"], ephemeral=True)
            
        embed = discord.Embed(title="Server Auto-Replies (`/nga`)", color=discord.Color.blue())
        description = []
        for trigger, data in sorted(guild_triggers.items()):
            line = f"• **`{trigger}`**"
            if data.get("alts"):
                line += f" (Alts: `{'`, `'.join(data['alts'])}`)"
            description.append(line)
        
        embed.description = "\n".join(description)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutoReply(bot))