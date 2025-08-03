import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
from pathlib import Path
import logging
import aiohttp
import xml.etree.ElementTree as ET
from typing import Dict, List

from .bot_admin import BotAdmin

# --- Personality Responses for this Cog ---
PERSONALITY = {
    "feed_added": "Okay, I'll keep an eye on that feed for `{tag}` and post any updates in {channel}.",
    "feed_removed": "Removed the `{tag}` feed. It was probably boring anyway.",
    "feed_not_found": "I can't find a feed with that tag.",
    "list_empty": "No Twitter feeds are configured for this server.",
    "list_title": "Configured Twitter Feeds",
    "invalid_url": "That doesn't look like a valid RSS feed URL. It should start with `http` and probably end with `.xml`.",
    "fetch_error": "I had trouble fetching the feed for `{tag}`. The service might be down or the URL is wrong."
}

class TwitterFeed(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.feeds_file = Path("data/twitter_feeds.json")
        # Data: {guild_id: [{"tag": str, "feed_url": str, "channel_id": int, "last_guid": str}, ...]}
        self.feed_data: Dict[str, List[Dict]] = self._load_json()
        self.check_feeds.start()

    def cog_unload(self):
        self.check_feeds.cancel()

    def _load_json(self) -> Dict:
        if not self.feeds_file.exists(): return {}
        try:
            with open(self.feeds_file, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError):
            self.logger.error(f"Error loading {self.feeds_file}", exc_info=True)
            return {}

    async def _save_json(self):
        try:
            with open(self.feeds_file, 'w', encoding='utf-8') as f: json.dump(self.feed_data, f, indent=2)
        except IOError:
            self.logger.error(f"Error saving {self.feeds_file}", exc_info=True)

    @tasks.loop(minutes=5)
    async def check_feeds(self):
        """Checks all configured RSS feeds for new posts."""
        await self.bot.wait_until_ready()
        self.logger.info("Checking Twitter RSS feeds...")
        
        for guild_id, feeds in self.feed_data.items():
            guild = self.bot.get_guild(int(guild_id))
            if not guild: continue
            
            for feed_config in feeds:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(feed_config["feed_url"]) as resp:
                            if resp.status != 200:
                                self.logger.warning(f"Failed to fetch RSS feed {feed_config['tag']} (Status: {resp.status})")
                                continue
                            
                            content = await resp.text()
                            root = ET.fromstring(content)
                            
                            # Find the latest item in the feed
                            latest_item = root.find("channel/item")
                            if latest_item is None: continue

                            # GUID is the unique identifier for a post
                            latest_guid = latest_item.find("guid").text
                            
                            if latest_guid != feed_config.get("last_guid"):
                                # This is a new tweet
                                link = latest_item.find("link").text
                                channel = guild.get_channel(feed_config["channel_id"])
                                if channel and channel.permissions_for(guild.me).send_messages:
                                    await channel.send(f"New post from **{feed_config['tag']}**:\n{link}")
                                    feed_config["last_guid"] = latest_guid
                                    await self._save_json()
                except Exception as e:
                    self.logger.error(f"Error processing feed '{feed_config['tag']}': {e}", exc_info=True)

    # --- Command Group ---
    feed_group = app_commands.Group(name="twitter-feed", description="Manage Twitter feed announcements.")

    @feed_group.command(name="add", description="Add a new Twitter account to follow via its RSS feed.")
    @app_commands.describe(
        tag="A short, unique name for this feed (e.g., 'Official News').",
        feed_url="The RSS feed URL for the Twitter account.",
        channel="The channel where new tweets should be posted."
    )
    @BotAdmin.is_bot_admin()
    async def add(self, interaction: discord.Interaction, tag: str, feed_url: str, channel: discord.TextChannel):
        if not feed_url.startswith("http"):
            return await interaction.response.send_message(PERSONALITY["invalid_url"], ephemeral=True)

        guild_id = str(interaction.guild_id)
        self.feed_data.setdefault(guild_id, [])
        
        # Check if a feed with this tag already exists
        if any(f["tag"].lower() == tag.lower() for f in self.feed_data[guild_id]):
            return await interaction.response.send_message("A feed with that tag already exists. Please choose a unique tag.", ephemeral=True)
            
        new_feed = {
            "tag": tag,
            "feed_url": feed_url,
            "channel_id": channel.id,
            "last_guid": None # Will be populated on the first successful check
        }
        self.feed_data[guild_id].append(new_feed)
        await self._save_json()
        
        await interaction.response.send_message(PERSONALITY["feed_added"].format(tag=tag, channel=channel.mention), ephemeral=True)

    @feed_group.command(name="remove", description="Stop following a Twitter feed.")
    @app_commands.describe(tag="The tag of the feed you want to remove.")
    @BotAdmin.is_bot_admin()
    async def remove(self, interaction: discord.Interaction, tag: str):
        guild_id = str(interaction.guild_id)
        feeds = self.feed_data.get(guild_id, [])
        
        feed_to_remove = next((f for f in feeds if f["tag"].lower() == tag.lower()), None)
        
        if not feed_to_remove:
            return await interaction.response.send_message(PERSONALITY["feed_not_found"], ephemeral=True)
            
        self.feed_data[guild_id].remove(feed_to_remove)
        await self._save_json()
        
        await interaction.response.send_message(PERSONALITY["feed_removed"].format(tag=feed_to_remove['tag']), ephemeral=True)

    # Autocomplete for the remove command
    @remove.autocomplete("tag")
    async def remove_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        guild_id = str(interaction.guild_id)
        feeds = self.feed_data.get(guild_id, [])
        return [
            app_commands.Choice(name=feed["tag"], value=feed["tag"])
            for feed in feeds if current.lower() in feed["tag"].lower()
        ][:25]

    @feed_group.command(name="list", description="List all configured Twitter feeds.")
    @BotAdmin.is_bot_admin()
    async def list_feeds(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        feeds = self.feed_data.get(guild_id, [])
        if not feeds:
            return await interaction.response.send_message(PERSONALITY["list_empty"], ephemeral=True)

        embed = discord.Embed(title=PERSONALITY["list_title"], color=discord.Color.blue())
        for feed in feeds:
            channel = interaction.guild.get_channel(feed['channel_id'])
            channel_mention = channel.mention if channel else "Unknown Channel"
            embed.add_field(name=f"🏷️ {feed['tag']}", value=f"**Channel:** {channel_mention}\n**Last Post ID:** `{feed.get('last_guid', 'None')}`", inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(TwitterFeed(bot))