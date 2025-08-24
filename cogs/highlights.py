import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
from pathlib import Path
import logging
from typing import Dict, Optional, List
import re
from datetime import datetime, time, timedelta, timezone

from .bot_admin import BotAdmin

# --- Personality Responses ---
PERSONALITY = {
    "channel_set": "Okay, I'll post the Weekly Highlights in {channel} from now on.",
    "test_run_start": "Fine, I'll generate the highlights for this week now. Give me a moment.",
    "no_posts": "I looked, but there weren't enough interesting messages in the chapel this week to create a highlight reel. How boring.",
    "highlights_title": "🏆 Weekly Chapel Highlights!"
}

# --- Configuration ---
# Day of the week (0=Monday, 6=Sunday) and UTC time to post the highlights
HIGHLIGHTS_SCHEDULE_DAY = 6 # Sunday
HIGHLIGHTS_SCHEDULE_TIME = time(hour=18, minute=0, tzinfo=timezone.utc) # 18:00 UTC

class Highlights(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # Use the same settings file as other cogs
        self.settings_file = Path("data/role_settings.json")
        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        self.post_weekly_highlights.start()

    def cog_unload(self):
        self.post_weekly_highlights.cancel()

    def _load_json(self, file_path: Path) -> Dict:
        if not file_path.exists(): return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError): return {}
    async def _save_json(self, data: dict, file_path: Path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except IOError: self.logger.error(f"Error saving {file_path}", exc_info=True)

    @tasks.loop(time=HIGHLIGHTS_SCHEDULE_TIME)
    async def post_weekly_highlights(self):
        """The main background task that runs weekly."""
        # Wait until the bot is ready
        await self.bot.wait_until_ready()
        
        # Check if today is the scheduled day
        if datetime.now(timezone.utc).weekday() != HIGHLIGHTS_SCHEDULE_DAY:
            return

        self.logger.info("It's time to post weekly highlights. Checking all configured guilds.")
        for guild in self.bot.guilds:
            try:
                await self._generate_highlights_for_guild(guild)
            except Exception as e:
                self.logger.error(f"Failed to generate highlights for guild {guild.id}: {e}", exc_info=True)

    async def _generate_highlights_for_guild(self, guild: discord.Guild, interaction: Optional[discord.Interaction] = None):
        """The core logic to find and post highlights for a single server."""
        gid_str = str(guild.id)
        config = self.settings_data.get(gid_str, {})
        
        chapel_config = config.get("chapel_config")
        highlights_channel_id = config.get("highlights_channel_id")
        
        if not chapel_config or not highlights_channel_id:
            self.logger.info(f"Skipping highlights for guild {guild.id}: not fully configured.")
            return

        chapel_channel = guild.get_channel(chapel_config["channel_id"])
        announce_channel = guild.get_channel(highlights_channel_id)
        if not chapel_channel or not announce_channel:
            self.logger.warning(f"Could not find chapel or announce channel for guild {guild.id}")
            return

        one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        top_messages = []

        async for message in chapel_channel.history(limit=500, after=one_week_ago):
            if message.author.id != self.bot.user.id or not message.embeds:
                continue

            embed = message.embeds[0]
            if not embed.footer or not embed.footer.text:
                continue
            
            # Extract star count from footer (e.g., "✨ 5 | #channel")
            match = re.search(r'(\d+)', embed.footer.text)
            if not match:
                continue
                
            star_count = int(match.group(1))
            jump_url_field = discord.utils.get(embed.fields, name="\u200b")
            
            if jump_url_field and jump_url_field.value:
                # Extract the actual URL from the markdown link
                url_match = re.search(r'\[.*\]\((.*)\)', jump_url_field.value)
                if url_match:
                    jump_url = url_match.group(1)
                    
                    top_messages.append({
                        "stars": star_count,
                        "author_name": embed.author.name,
                        "content_preview": embed.description[:100] + "..." if embed.description and len(embed.description) > 100 else embed.description or "*No text content*",
                        "jump_url": jump_url
                    })

        if len(top_messages) < 3:
            self.logger.info(f"Not enough posts ({len(top_messages)}) in guild {guild.id} for highlights.")
            if interaction: await interaction.followup.send(PERSONALITY["no_posts"], ephemeral=True)
            return

        # Sort by star count and get the top 3
        top_3 = sorted(top_messages, key=lambda x: x["stars"], reverse=True)[:3]

        highlights_embed = discord.Embed(
            title=PERSONALITY["highlights_title"],
            description="Here are the most popular messages from the chapel this week!",
            color=0xFEE75C # Gold
        )
        for i, post in enumerate(top_3):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉"
            highlights_embed.add_field(
                name=f"{medal} Top Post by {post['author_name']} ({post['stars']} Stars)",
                value=f"> {post['content_preview']}\n[**Jump to Message**]({post['jump_url']})",
                inline=False
            )
        
        await announce_channel.send(embed=highlights_embed)
        if interaction: await interaction.followup.send("✅ Highlights have been generated and posted!", ephemeral=True)

    # --- Admin Command Group ---
    admin_group = app_commands.Group(name="highlights-admin", description="Admin commands for the weekly highlights feature.")

    @admin_group.command(name="set-channel", description="Set the channel where weekly highlights will be posted.")
    @app_commands.describe(channel="The channel for highlight announcements.")
    @BotAdmin.is_bot_admin()
    async def set_channel(self, i: discord.Interaction, channel: discord.TextChannel):
        gid_str = str(i.guild.id)
        self.settings_data.setdefault(gid_str, {})["highlights_channel_id"] = channel.id
        await self._save_json(self.settings_data, self.settings_file)
        await i.response.send_message(PERSONALITY["channel_set"].format(channel=channel.mention), ephemeral=True)

    @admin_group.command(name="test-run", description="Manually generate and post this week's highlights now.")
    @BotAdmin.is_bot_admin()
    async def test_run(self, i: discord.Interaction):
        await i.response.send_message(PERSONALITY["test_run_start"], ephemeral=True)
        await self._generate_highlights_for_guild(i.guild, interaction=i)

async def setup(bot):
    await bot.add_cog(Highlights(bot))