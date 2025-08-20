import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
import re
from typing import Dict, Optional, Union

from .bot_admin import BotAdmin

# --- Personality Responses ---
PERSONALITY = {
    "setup_success": "Done. Chapel is now configured. I'll watch for `{emote}` reactions in this server.",
    "invalid_emote": "That doesn't look like a valid custom emote from this server."
}

class CopyChapel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.settings_file = Path("data/role_settings.json")
        self.message_map_file = Path("data/chapel_message_map.json")

        # Ensure data directory exists
        Path("data").mkdir(exist_ok=True)

        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        self.message_map: Dict[str, Dict[str, int]] = self._load_json(self.message_map_file)
        self.config_cache: Dict[int, Dict] = {}

    def _load_json(self, file_path: Path) -> Dict:
        if not file_path.exists(): 
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f: 
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Error loading {file_path}: {e}")
            return {}

    async def _save_json(self, data: dict, file_path: Path):
        try:
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f: 
                json.dump(data, f, indent=2)
            self.logger.debug(f"Saved data to {file_path}")
        except IOError as e: 
            self.logger.error(f"Error saving {file_path}: {e}", exc_info=True)
            
    def _get_config(self, guild_id: int) -> Optional[Dict]:
        if guild_id in self.config_cache: 
            return self.config_cache[guild_id]
        
        guild_str = str(guild_id)
        guild_data = self.settings_data.get(guild_str, {})
        config = guild_data.get("chapel_config")
        
        if config and all(k in config for k in ["channel_id", "emote"]):
            config.setdefault("threshold", 2)  # Changed default from 1 to 2
            self.config_cache[guild_id] = config
            self.logger.debug(f"Loaded config for guild {guild_id}: {config}")
            return config
        else:
            self.logger.debug(f"No valid config found for guild {guild_id}. Data: {guild_data}")
        return None

    def _invalidate_cache(self, guild_id: int):
        self.config_cache.pop(guild_id, None)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        self.logger.debug(f"Reaction added: {payload.emoji} in guild {payload.guild_id}")
        await self._handle_reaction(payload, is_add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        self.logger.debug(f"Reaction removed: {payload.emoji} in guild {payload.guild_id}")
        await self._handle_reaction(payload, is_add=False)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, is_add: bool):
        if not payload.guild_id: 
            self.logger.debug("No guild_id in payload, skipping")
            return
            
        config = self._get_config(payload.guild_id)
        if not config:
            self.logger.debug(f"No config found for guild {payload.guild_id}")
            return
            
        # Convert emoji to string for comparison
        emoji_str = str(payload.emoji)
        config_emoji = config["emote"]
        
        self.logger.debug(f"Comparing emojis: payload='{emoji_str}' vs config='{config_emoji}'")
        
        if emoji_str != config_emoji:
            self.logger.debug(f"Emoji mismatch: {emoji_str} != {config_emoji}")
            return

        self.logger.info(f"Processing chapel reaction {emoji_str} in guild {payload.guild_id}")

        try:
            # Get the channel and message
            channel = self.bot.get_channel(payload.channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(payload.channel_id)
            
            if not isinstance(channel, discord.TextChannel): 
                self.logger.debug(f"Channel {payload.channel_id} is not a text channel")
                return
                
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden) as e:
            self.logger.error(f"Could not fetch message {payload.message_id}: {e}")
            return

        # Skip bot messages
        if message.author.bot:
            self.logger.debug("Skipping bot message")
            return

        # Get reaction count AFTER fetching message to get accurate count
        reaction = discord.utils.get(message.reactions, emoji=payload.emoji)
        reaction_count = reaction.count if reaction else 0
        
        # Check if bot has already reacted
        bot_already_reacted = False
        if reaction:
            async for user in reaction.users():
                if user.id == self.bot.user.id:
                    bot_already_reacted = True
                    break
        
        self.logger.info(f"Reaction count for message {message.id}: {reaction_count}, threshold: {config['threshold']}, bot reacted: {bot_already_reacted}")

        # Get chapel channel
        chapel_channel = self.bot.get_channel(config["channel_id"])
        if not chapel_channel:
            try:
                chapel_channel = await self.bot.fetch_channel(config["channel_id"])
            except (discord.NotFound, discord.Forbidden) as e:
                self.logger.error(f"Could not access chapel channel {config['channel_id']}: {e}")
                return
        
        gid_str, msg_id_str = str(payload.guild_id), str(message.id)
        self.message_map.setdefault(gid_str, {})
        existing_chapel_id = self.message_map[gid_str].get(msg_id_str)

        # If this is an add event and the user is not the bot
        if is_add and payload.user_id != self.bot.user.id:
            # Add bot reaction automatically when a user reacts (if bot hasn't already)
            if not bot_already_reacted:
                try:
                    await message.add_reaction(payload.emoji)
                    reaction_count += 1  # Update count since bot just added a reaction
                    self.logger.debug(f"Bot automatically added reaction to boost count to {reaction_count}")
                except (discord.Forbidden, discord.HTTPException) as e:
                    self.logger.debug(f"Could not add bot reaction: {e}")

        # Only create chapel message if bot just reacted and no chapel message exists yet
        if is_add and payload.user_id == self.bot.user.id and not existing_chapel_id:
            self.logger.info(f"Bot reacted, creating new chapel message")
            
            try:
                embed = await self._create_chapel_embed(message, payload.emoji, reaction_count)
                chapel_message = await chapel_channel.send(embed=embed)
                self.message_map[gid_str][msg_id_str] = chapel_message.id
                await self._save_json(self.message_map, self.message_map_file)
                self.logger.info(f"Created new chapel message {chapel_message.id}")
                    
            except discord.Forbidden as e:
                self.logger.error(f"No permission to send messages in chapel channel: {e}")
            except Exception as e:
                self.logger.error(f"Error creating chapel message: {e}", exc_info=True)

    async def _create_chapel_embed(self, message: discord.Message, emoji: Union[discord.Emoji, discord.PartialEmoji, str], count: int) -> discord.Embed:
        """Creates an embed that mimics Discord's message format."""
        
        # Main embed with message content - using a more neutral color
        embed = discord.Embed(
            color=0x5865F2,  # Discord blurple color
            timestamp=message.created_at
        )
        
        # Set author (message sender)
        embed.set_author(
            name=message.author.display_name, 
            icon_url=message.author.display_avatar.url
        )
        
        # Handle replies first
        description_parts = []
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            replied_to = message.reference.resolved
            reply_author = replied_to.author.display_name
            reply_content = replied_to.content or "*No text content*"
            
            if len(reply_content) > 50:
                reply_content = reply_content[:50] + "..."
            
            description_parts.append(f"**Replied to @{reply_author}**")
            description_parts.append(f"> {reply_content}")
            description_parts.append("")  # Empty line
        
        # Add main message content
        if message.content:
            description_parts.append(message.content)
        
        # Handle attachments
        if message.attachments:
            if description_parts and description_parts[-1]:  # Add spacing if there's content above
                description_parts.append("")
                
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith('image/'):
                    # Set the first image as embed image
                    if not embed.image:
                        embed.set_image(url=attachment.url)
                        description_parts.append(f"🖼️ **{attachment.filename}**")
                    else:
                        description_parts.append(f"🖼️ [{attachment.filename}]({attachment.url})")
                else:
                    description_parts.append(f"📎 [{attachment.filename}]({attachment.url})")
        
        # Set the description
        embed.description = "\n".join(description_parts) if description_parts else "*No content*"
        
        # Add reaction info and channel link in a single field without labels
        embed.add_field(
            name="\u200b",  # Invisible character for empty field name
            value=f"[#{message.channel.name}]({message.jump_url}) | {emoji} {count}", 
            inline=False
        )
        
        return embed

    # --- Admin Command Group ---
    admin_group = app_commands.Group(name="chapel-admin", description="Admin commands for the copy chapel feature.")
    
    async def _is_bot_admin_fallback(self, user_id: int) -> bool:
        """Fallback admin check if BotAdmin is not available"""
        try:
            return await BotAdmin.is_bot_admin_check(user_id)
        except:
            return False

    @admin_group.command(name="set-channel", description="Set the channel where quoted messages will be sent.")
    @app_commands.describe(channel="The channel to use as the chapel.")
    async def set_channel(self, i: discord.Interaction, channel: discord.TextChannel):
        # Check if user has administrator permissions or is bot admin
        if not (i.user.guild_permissions.administrator or await self._is_bot_admin_fallback(i.user.id)):
            await i.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
            return
            
        gid_str = str(i.guild.id)
        self.settings_data.setdefault(gid_str, {}).setdefault("chapel_config", {})["channel_id"] = channel.id
        await self._save_json(self.settings_data, self.settings_file)
        self._invalidate_cache(i.guild.id)
        await i.response.send_message(f"✅ Chapel channel set to {channel.mention}.", ephemeral=True)
        self.logger.info(f"Chapel channel set to {channel.id} for guild {i.guild.id}")

    @admin_group.command(name="set-emote", description="Set the emote to trigger the chapel (custom or unicode like ✨).")
    @app_commands.describe(emote="The emote from this server or any unicode emoji like ✨")
    async def set_emote(self, i: discord.Interaction, emote: str):
        # Check if user has administrator permissions or is bot admin
        if not (i.user.guild_permissions.administrator or await self._is_bot_admin_fallback(i.user.id)):
            await i.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
            return
        
        # Try to match custom emoji pattern first
        match = re.match(r'<a?:([a-zA-Z0-9_]+):([0-9]+)>', emote)
        if match:
            # It's a custom emoji
            emoji_id = int(match.group(2))
            found_emote = self.bot.get_emoji(emoji_id)
            if not found_emote or found_emote.guild.id != i.guild.id:
                return await i.response.send_message(PERSONALITY["invalid_emote"], ephemeral=True)
            emote_str = str(found_emote)
        else:
            # Assume it's a unicode emoji (like ✨, 🎉, etc.)
            emote_str = emote.strip()
        
        gid_str = str(i.guild.id)
        self.settings_data.setdefault(gid_str, {}).setdefault("chapel_config", {})["emote"] = emote_str
        await self._save_json(self.settings_data, self.settings_file)
        self._invalidate_cache(i.guild.id)
        await i.response.send_message(f"✅ Chapel emote set to {emote_str}.", ephemeral=True)
        self.logger.info(f"Chapel emote set to '{emote_str}' for guild {i.guild.id}")

    @admin_group.command(name="set-threshold", description="Set how many reactions are needed to post a message (Default: 2).")
    @app_commands.describe(count="The number of reactions required (e.g., 3).")
    async def set_threshold(self, i: discord.Interaction, count: app_commands.Range[int, 1, 100]):
        # Check if user has administrator permissions or is bot admin
        if not (i.user.guild_permissions.administrator or await self._is_bot_admin_fallback(i.user.id)):
            await i.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
            return
            
        gid_str = str(i.guild.id)
        self.settings_data.setdefault(gid_str, {}).setdefault("chapel_config", {})["threshold"] = count
        await self._save_json(self.settings_data, self.settings_file)
        self._invalidate_cache(i.guild.id)
        await i.response.send_message(f"✅ Chapel threshold set to **{count}**.", ephemeral=True)
        self.logger.info(f"Chapel threshold set to {count} for guild {i.guild.id}")

    @admin_group.command(name="status", description="Check the current chapel configuration.")
    async def status(self, i: discord.Interaction):
        # Check if user has administrator permissions or is bot admin
        if not (i.user.guild_permissions.administrator or await self._is_bot_admin_fallback(i.user.id)):
            await i.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
            return
        config = self._get_config(i.guild.id)
        if not config:
            await i.response.send_message("❌ Chapel is not configured for this server.", ephemeral=True)
            return
            
        channel = self.bot.get_channel(config["channel_id"])
        channel_mention = channel.mention if channel else f"<#{config['channel_id']}> (channel not found)"
        
        embed = discord.Embed(title="Chapel Configuration", color=0xFEE75C)
        embed.add_field(name="Channel", value=channel_mention, inline=True)
        embed.add_field(name="Emote", value=config["emote"], inline=True)
        embed.add_field(name="Threshold", value=str(config["threshold"]), inline=True)
        
        await i.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(CopyChapel(bot))