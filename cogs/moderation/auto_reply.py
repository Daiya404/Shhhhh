# cogs/moderation/auto_reply.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
from typing import Optional

# Imports from our new project structure
from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import BotAdmin

class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["auto_reply"]
        self.data_manager = self.bot.data_manager
        self.regex_cache = {}

    @commands.Cog.listener()
    async def on_ready(self):
        """Builds the regex cache for all guilds when the cog is ready."""
        self.logger.info("Building Auto-Reply regex cache...")
        all_replies = await self.data_manager.get_data("auto_replies")
        for guild_id, triggers in all_replies.items():
            self._update_regex_for_guild(guild_id, triggers)
        self.logger.info("Auto-Reply regex cache built.")

    def _update_regex_for_guild(self, guild_id: str, guild_triggers: dict):
        """Compiles and caches a single regex pattern for all triggers in a guild."""
        all_trigger_words = []
        for trigger, data in guild_triggers.items():
            all_trigger_words.append(re.escape(trigger))
            all_trigger_words.extend(re.escape(alt) for alt in data.get("alts", []))
        
        if not all_trigger_words:
            self.regex_cache[guild_id] = None
            return
            
        pattern = r'\b(' + '|'.join(all_trigger_words) + r')\b'
        self.regex_cache[guild_id] = re.compile(pattern, re.IGNORECASE)

    async def check_for_reply(self, message: discord.Message) -> bool:
        """Called by the main on_message event. Returns True if a reply was sent."""
        # This logic remains the same and is already correct.
        if not message.guild: return False
        guild_id = str(message.guild.id)
        guild_regex = self.regex_cache.get(guild_id)
        if not guild_regex: return False
        match = guild_regex.search(message.content)
        if not match: return False
        triggered_word = match.group(1).lower()
        all_replies = await self.data_manager.get_data("auto_replies")
        guild_triggers = all_replies.get(guild_id, {})
        for main_trigger, data in guild_triggers.items():
            if triggered_word == main_trigger.lower() or triggered_word in [alt.lower() for alt in data.get("alts", [])]:
                try:
                    await message.reply(data["reply"], mention_author=False)
                    return True
                except (discord.Forbidden, discord.HTTPException) as e:
                    self.logger.error(f"Failed to send auto-reply for trigger '{triggered_word}': {e}")
                return True
        return False

    # --- NEW COMBINED COMMANDS ---

    @app_commands.command(name="autoreply", description="Add or remove an auto-reply trigger.")
    @BotAdmin.is_bot_admin()
    @app_commands.describe(
        action="Whether to add a new trigger or remove an existing one.",
        trigger="The word/phrase to listen for.",
        reply="The reply text or URL (only needed for 'add')."
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
    ])
    async def manage_autoreply(self, interaction: discord.Interaction, action: str, trigger: str, reply: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        if action == "add" and not reply:
            return await interaction.followup.send("You must provide a `reply` when adding a trigger. Obviously.")

        all_replies = await self.data_manager.get_data("auto_replies")
        guild_id = str(interaction.guild_id)
        guild_triggers = all_replies.setdefault(guild_id, {})
        trigger_key = trigger.lower().strip()

        if action == "add":
            if trigger_key in guild_triggers:
                return await interaction.followup.send(self.personality["already_exists"])
            
            guild_triggers[trigger_key] = {"reply": reply, "alts": []}
            response_msg = self.personality["trigger_set"].format(trigger=trigger)
        
        elif action == "remove":
            if trigger_key not in guild_triggers:
                return await interaction.followup.send(self.personality["trigger_not_found"])
            
            del guild_triggers[trigger_key]
            response_msg = self.personality["trigger_removed"].format(trigger=trigger)

        await self.data_manager.save_data("auto_replies", all_replies)
        self._update_regex_for_guild(guild_id, guild_triggers)
        await interaction.followup.send(response_msg)

    @app_commands.command(name="autoreply-alt", description="Add multiple alternative words to an existing trigger.")
    @BotAdmin.is_bot_admin()
    @app_commands.describe(
        main_trigger="The trigger to add alternatives for.",
        alternatives="The new alternative words, separated by spaces."
    )
    async def add_alts_bulk(self, interaction: discord.Interaction, main_trigger: str, alternatives: str):
        await interaction.response.defer(ephemeral=True)
        
        all_replies = await self.data_manager.get_data("auto_replies")
        guild_id = str(interaction.guild_id)
        guild_triggers = all_replies.get(guild_id, {})
        main_key = main_trigger.lower().strip()

        if main_key not in guild_triggers:
            return await interaction.followup.send(self.personality["trigger_not_found"])

        # This is the new logic for bulk adding
        alts_to_add = alternatives.strip().lower().split()
        if not alts_to_add:
            return await interaction.followup.send(self.personality["error_empty"])

        existing_alts_set = set(guild_triggers[main_key].setdefault("alts", []))
        actually_added = []
        
        for alt in alts_to_add:
            if alt not in existing_alts_set and alt != main_key:
                existing_alts_set.add(alt)
                actually_added.append(alt)

        if not actually_added:
            return await interaction.followup.send(self.personality["already_exists"])

        guild_triggers[main_key]["alts"] = list(existing_alts_set)
        await self.data_manager.save_data("auto_replies", all_replies)
        self._update_regex_for_guild(guild_id, guild_triggers)
        
        await interaction.followup.send(f"Okay, I've added `{', '.join(actually_added)}` as alternatives for `{main_trigger}`.")

    @app_commands.command(name="autoreply-list", description="List all configured auto-replies for this server.")
    async def list_replies(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        all_replies = await self.data_manager.get_data("auto_replies")
        guild_triggers = all_replies.get(str(interaction.guild_id), {})
        
        if not guild_triggers:
            return await interaction.followup.send(self.personality["list_empty"])

        embed = discord.Embed(title="Server Auto-Replies", color=discord.Color.blue())
        description = []
        for trigger, data in sorted(guild_triggers.items()):
            line = f"• **`{trigger}`**"
            if data.get("alts"):
                line += f" (Alts: `{'`, `'.join(data['alts'])}`)"
            description.append(line)
        
        embed.description = "\n".join(description)
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AutoReply(bot))