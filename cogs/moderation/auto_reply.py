# cogs/moderation/auto_reply.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import time
from typing import Optional

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["auto_reply"]
        self.data_manager = self.bot.data_manager
        
        # --- TUNED RATE LIMIT ---
        self.COOLDOWN_SECONDS = 1
        self.channel_cooldowns = {}
        
        self.all_replies_cache = {}
        self.regex_cache = {}

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info("Loading all auto-replies into memory and building regex cache...")
        self.all_replies_cache = await self.data_manager.get_data("auto_replies")
        for guild_id, triggers in self.all_replies_cache.items():
            self._update_regex_for_guild(guild_id, triggers)
        self.logger.info("Auto-Reply cache is ready.")

    def _update_regex_for_guild(self, guild_id: str, guild_triggers: dict):
        all_trigger_words = [re.escape(trigger) for trigger in guild_triggers]
        for data in guild_triggers.values():
            all_trigger_words.extend(re.escape(alt) for alt in data.get("alts", []))
        if not all_trigger_words:
            self.regex_cache[guild_id] = None
            return
        pattern = r'\b(' + '|'.join(all_trigger_words) + r')\b'
        self.regex_cache[guild_id] = re.compile(pattern, re.IGNORECASE)

    async def check_for_reply(self, message: discord.Message) -> bool:
        """Ultra-fast message check WITH rate limiting."""
        if not message.guild: return False
        
        now = time.time()
        channel_id = message.channel.id
        last_reply_time = self.channel_cooldowns.get(channel_id, 0)
        
        if now - last_reply_time < self.COOLDOWN_SECONDS:
            return False

        guild_id = str(message.guild.id)
        guild_regex = self.regex_cache.get(guild_id)
        if not guild_regex: return False

        match = guild_regex.search(message.content)
        if not match: return False
        
        triggered_word = match.group(1).lower()
        guild_triggers = self.all_replies_cache.get(guild_id, {})
        
        for main_trigger, data in guild_triggers.items():
            if triggered_word == main_trigger.lower() or triggered_word in [alt.lower() for alt in data.get("alts", [])]:
                try:
                    self.channel_cooldowns[channel_id] = now
                    await message.reply(data["reply"], mention_author=False)
                except (discord.Forbidden, discord.HTTPException) as e:
                    self.logger.error(f"Failed to send auto-reply, but cooldown was set: {e}")
                return True
        return False

    # --- Commands (No changes needed below this line) ---

    @app_commands.command(name="autoreply", description="Add or remove an auto-reply trigger.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(action="Add a new trigger or remove an existing one.", trigger="The word/phrase to listen for.", reply="The reply text or URL (only needed for 'add').")
    @app_commands.choices(action=[app_commands.Choice(name="Add", value="add"), app_commands.Choice(name="Remove", value="remove")])
    async def manage_autoreply(self, interaction: discord.Interaction, action: str, trigger: str, reply: Optional[str] = None):
        await interaction.response.defer()
        if action == "add" and not reply:
            return await interaction.followup.send("You must provide a `reply` when adding a trigger. Obviously.", ephemeral=True)
        guild_id = str(interaction.guild_id)
        guild_triggers = self.all_replies_cache.setdefault(guild_id, {})
        trigger_key = trigger.lower().strip()
        response_msg = ""
        if action == "add":
            if trigger_key in guild_triggers:
                return await interaction.followup.send(self.personality["already_exists"], ephemeral=True)
            guild_triggers[trigger_key] = {"reply": reply, "alts": []}
            response_msg = self.personality["trigger_set"].format(trigger=f"`{trigger}`")
        elif action == "remove":
            if trigger_key not in guild_triggers:
                return await interaction.followup.send(self.personality["trigger_not_found"], ephemeral=True)
            del guild_triggers[trigger_key]
            response_msg = self.personality["trigger_removed"].format(trigger=f"`{trigger}`")
        await self.data_manager.save_data("auto_replies", self.all_replies_cache)
        self._update_regex_for_guild(guild_id, guild_triggers)
        await interaction.followup.send(response_msg)

    @app_commands.command(name="autoreply-alt", description="Add multiple alternative words to an existing trigger.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(main_trigger="The trigger to add alternatives for.", alternatives="The new alternative words, separated by spaces.")
    async def add_alts_bulk(self, interaction: discord.Interaction, main_trigger: str, alternatives: str):
        await interaction.response.defer()
        guild_id = str(interaction.guild_id)
        guild_triggers = self.all_replies_cache.get(guild_id, {})
        main_key = main_trigger.lower().strip()
        if main_key not in guild_triggers:
            return await interaction.followup.send(self.personality["trigger_not_found"], ephemeral=True)
        alts_to_add = alternatives.strip().lower().split()
        if not alts_to_add:
            return await interaction.followup.send(self.personality["error_empty"], ephemeral=True)
        existing_alts_set = set(guild_triggers[main_key].setdefault("alts", []))
        actually_added = [alt for alt in alts_to_add if alt not in existing_alts_set and alt != main_key]
        if not actually_added:
            return await interaction.followup.send(self.personality["already_exists"], ephemeral=True)
        existing_alts_set.update(actually_added)
        guild_triggers[main_key]["alts"] = sorted(list(existing_alts_set))
        await self.data_manager.save_data("auto_replies", self.all_replies_cache)
        self._update_regex_for_guild(guild_id, guild_triggers)
        await interaction.followup.send(f"Okay, I've added `{', '.join(actually_added)}` as alternatives for `{main_trigger}`.")

    @app_commands.command(name="autoreply-list", description="List all configured auto-replies for this server.")
    async def list_replies(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_triggers = self.all_replies_cache.get(str(interaction.guild.id), {})
        if not guild_triggers:
            return await interaction.followup.send(self.personality["list_empty"])
        embed = discord.Embed(title="Server Auto-Replies", color=discord.Color.blue())
        description = [f"• **`{trigger}`**" + (f" (Alts: `{'`, `'.join(data['alts'])}`)" if data.get("alts") else "") for trigger, data in sorted(guild_triggers.items())]
        embed.description = "\n".join(description)
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AutoReply(bot))