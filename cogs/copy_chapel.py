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
            config.setdefault("threshold", 1)
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
        
        self.logger.info(f"Reaction count for message {message.id}: {reaction_count}, threshold: {config['threshold']}")

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

        if reaction_count >= config["threshold"]:
            self.logger.info(f"Threshold met, posting/updating chapel message")
            
            # Only add bot reaction when threshold is first met and we're creating a new message
            if is_add and not existing_chapel_id:
                try:
                    bot_already_reacted = False
                    if reaction:
                        async for user in reaction.users():
                            if user.id == self.bot.user.id:
                                bot_already_reacted = True
                                break
                    
                    if not bot_already_reacted:
                        await message.add_reaction(payload.emoji)
                        self.logger.debug(f"Bot added reaction to boost count")
                except (discord.Forbidden, discord.HTTPException) as e:
                    self.logger.debug(f"Could not add bot reaction: {e}")
            
            try:
                embed = await self._create_chapel_embed(message, payload.emoji, reaction_count)
                
                if existing_chapel_id:
                    try:
                        chapel_message = await chapel_channel.fetch_message(existing_chapel_id)
                        await chapel_message.edit(embed=embed)
                        self.logger.info(f"Updated existing chapel message {existing_chapel_id}")
                    except discord.NotFound:
                        self.logger.info(f"Existing chapel message {existing_chapel_id} not found, creating new one")
                        chapel_message = await chapel_channel.send(embed=embed)
                        self.message_map[gid_str][msg_id_str] = chapel_message.id
                        await self._save_json(self.message_map, self.message_map_file)
                else:
                    chapel_message = await chapel_channel.send(embed=embed)
                    self.message_map[gid_str][msg_id_str] = chapel_message.id
                    await self._save_json(self.message_map, self.message_map_file)
                    self.logger.info(f"Created new chapel message {chapel_message.id}")
                    
            except discord.Forbidden as e:
                self.logger.error(f"No permission to send messages in chapel channel: {e}")
            except Exception as e:
                self.logger.error(f"Error creating/updating chapel message: {e}", exc_info=True)
        
        elif existing_chapel_id and not is_add:  # Only delete on reaction removal
            self.logger.info(f"Threshold not met after removal, removing chapel message {existing_chapel_id}")
            try:
                chapel_message = await chapel_channel.fetch_message(existing_chapel_id)
                await chapel_message.delete()
                self.logger.info(f"Deleted chapel message {existing_chapel_id}")
            except (discord.NotFound, discord.Forbidden) as e:
                self.logger.debug(f"Could not delete chapel message {existing_chapel_id}: {e}")
                
            if self.message_map[gid_str].pop(msg_id_str, None):
                await self._save_json(self.message_map, self.message_map_file)

    async def _create_chapel_embed(self, message: discord.Message, emoji: Union[discord.Emoji, discord.PartialEmoji, str], count: int) -> discord.Embed:
        """Creates an embed that mimics Discord's message format."""
        
        # Main embed with message content
        embed = discord.Embed(
            color=0x2F3136,  # Discord dark theme color
            timestamp=message.created_at
        )
        
        # Set author (message sender)
        embed.set_author(
            name=message.author.display_name, 
            icon_url=message.author.display_avatar.url
        )
        
        # Message content
        if message.content:
            embed.description = message.content
        else:
            embed.description = "*No text content*"
        
        # Handle replies
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            replied_to = message.reference.resolved
            reply_author = replied_to.author.display_name
            reply_content = replied_to.content or "*No text content*"
            
            if len(reply_content) > 100:
                reply_content = reply_content[:100] + "..."
            
            # Add reply info at the top of description
            reply_text = f"**Replied to @{reply_author}**\n> {reply_content}\n\n"
            embed.description = reply_text + (embed.description or "")
        
        # Handle attachments
        if message.attachments:
            attachment_urls = []
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith('image/'):
                    # Set the first image as embed image
                    if not embed.image:
                        embed.set_image(url=attachment.url)
                attachment_urls.append(f"[{attachment.filename}]({attachment.url})")
            
            if attachment_urls:
                if embed.description and embed.description != "*No text content*":
                    embed.description += f"\n\n**Attachments:**\n" + "\n".join(attachment_urls)
                else:
                    embed.description = f"**Attachments:**\n" + "\n".join(attachment_urls)
        
        # Add reaction info and jump link in footer
        embed.set_footer(text=f"{emoji} {count} | #{message.channel.name} | Jump to message")
        embed.url = message.jump_url
        
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

    @admin_group.command(name="set-emote", description="Set the custom emote to trigger the chapel.")
    @app_commands.describe(emote="The custom emote from this server.")
    async def set_emote(self, i: discord.Interaction, emote: str):
        # Check if user has administrator permissions or is bot admin
        if not (i.user.guild_permissions.administrator or await self._is_bot_admin_fallback(i.user.id)):
            await i.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
            return
            
        # Try to match custom emoji pattern
        match = re.match(r'<a?:([a-zA-Z0-9_]+):([0-9]+)>', emote)
        if match:
            emoji_id = int(match.group(2))
            found_emote = self.bot.get_emoji(emoji_id)
            if not found_emote or found_emote.guild.id != i.guild.id:
                return await i.response.send_message(PERSONALITY["invalid_emote"], ephemeral=True)
            emote_str = str(found_emote)
        else:
            # Might be a unicode emoji
            emote_str = emote
        
        gid_str = str(i.guild.id)
        self.settings_data.setdefault(gid_str, {}).setdefault("chapel_config", {})["emote"] = emote_str
        await self._save_json(self.settings_data, self.settings_file)
        self._invalidate_cache(i.guild.id)
        await i.response.send_message(f"✅ Chapel emote set to {emote_str}.", ephemeral=True)
        self.logger.info(f"Chapel emote set to '{emote_str}' for guild {i.guild.id}")

    @admin_group.command(name="set-threshold", description="Set how many reactions are needed to post a message (Default: 1).")
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