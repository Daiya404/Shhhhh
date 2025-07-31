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
    "global_enabled": "You're lucky I'm here to fix your broken embeds. Link fixer is now **ON** for the server.",
    "global_disabled": "Fine, I'll stop fixing links for everyone. The system is now **OFF** for the server.",
    "personal_opt_out": "Alright, I'll leave your links alone from now on. Your personal link fixing is **OFF**.",
    "personal_opt_in": "Hmph. So you need my help after all? Fine, I'll fix your links again. Your personal link fixing is **ON**.",
    "fix_message": "I fixed the embed for {user}... Not that you asked."
}

class LinkFixer(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.settings_file = Path("data/link_fixer_settings.json")
        
        # Data: {guild_id: {"global_enabled": bool, "user_opt_out": [user_id, ...]}}
        self.settings: Dict[str, Dict] = self._load_json()
        
        # Regex to find twitter and x links
        self.link_pattern = re.compile(
            r'https?:\/\/(?:www\.)?(?:twitter|x)\.com\/[a-zA-Z0-9_]+\/status\/[0-9]+'
        )

    # --- Data Handling ---
    def _load_json(self) -> Dict:
        if not self.settings_file.exists(): return {}
        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Error loading {self.settings_file}: {e}")
            return {}

    async def _save_json(self):
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
        except IOError as e:
            self.logger.error(f"Error saving {self.settings_file}: {e}")

    # --- Core Logic for the "Traffic Cop" ---
    async def check_and_fix_link(self, message: discord.Message) -> bool:
        """Checks for a fixable link and handles it. Returns True if handled."""
        if not message.guild: return False

        guild_id = str(message.guild.id)
        
        # Check if the feature is globally enabled for the server
        guild_settings = self.settings.get(guild_id, {"global_enabled": True})
        if not guild_settings.get("global_enabled", True):
            return False

        # Check if the user has personally opted out
        if message.author.id in guild_settings.get("user_opt_out", []):
            return False
            
        # Find all twitter/x links in the message
        found_links = self.link_pattern.findall(message.content)
        if not found_links:
            return False

        # Replace links
        fixed_content = message.content
        for link in found_links:
            if "twitter.com" in link:
                fixed_content = fixed_content.replace("twitter.com", "vxtwitter.com")
            elif "x.com" in link:
                fixed_content = fixed_content.replace("x.com", "vxtwitter.com")

        # If the content hasn't changed, do nothing (shouldn't happen)
        if fixed_content == message.content:
            return False
            
        try:
            # Create a webhook to impersonate the user for a seamless look
            webhook = await message.channel.create_webhook(name=message.author.display_name)
            await webhook.send(
                content=fixed_content,
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url,
                allowed_mentions=discord.AllowedMentions.none() # Prevents pinging people again
            )
            await webhook.delete()
            
            # Delete the original problematic message
            await message.delete()

        except discord.Forbidden:
            self.logger.warning(f"Missing permissions to fix link in {message.channel.name} (Need Manage Webhooks & Manage Messages).")
        except Exception as e:
            self.logger.error(f"Failed to fix link: {e}", exc_info=True)
            
        return True # We handled the message, so the traffic cop should stop

    # --- Command Group ---
    fixer_group = app_commands.Group(name="linkfixer", description="Commands to manage the link fixing feature.")

    @fixer_group.command(name="toggle-global", description="Turn the link fixer ON or OFF for the entire server.")
    @BotAdmin.is_bot_admin()
    async def toggle_global(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        
        # Get current setting, default to True if not set
        current_status = self.settings.get(guild_id, {}).get("global_enabled", True)
        new_status = not current_status
        
        # Update setting
        self.settings.setdefault(guild_id, {})["global_enabled"] = new_status
        await self._save_json()
        
        response = PERSONALITY["global_enabled"] if new_status else PERSONALITY["global_disabled"]
        await interaction.response.send_message(response, ephemeral=True)

    @fixer_group.command(name="toggle-personal", description="Turn link fixing ON or OFF for your own messages.")
    async def toggle_personal(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        user_id = interaction.user.id
        
        self.settings.setdefault(guild_id, {"user_opt_out": []})
        opt_out_list = self.settings[guild_id].setdefault("user_opt_out", [])
        
        if user_id in opt_out_list:
            # User is currently opted out, so we opt them back in
            opt_out_list.remove(user_id)
            response = PERSONALITY["personal_opt_in"]
        else:
            # User is currently opted in, so we opt them out
            opt_out_list.append(user_id)
            response = PERSONALITY["personal_opt_out"]
            
        await self._save_json()
        await interaction.response.send_message(response, ephemeral=True)

async def setup(bot):
    await bot.add_cog(LinkFixer(bot))