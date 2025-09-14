import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
from typing import Dict, Optional, Union

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

class CopyChapel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["copy_chapel"]
        self.data_manager = self.bot.data_manager

        # --- OPTIMIZATION: In-memory caches for high-frequency events ---
        self.settings_cache: Dict[str, Dict] = {}
        self.message_map_cache: Dict[str, Dict[str, int]] = {}

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """A local check to see if the copy_chapel feature is enabled."""
        feature_manager = self.bot.get_cog("FeatureManager")
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, "copy_chapel"):
            await interaction.response.send_message("Hmph. The Custom Roles feature is disabled on this server.", ephemeral=True)
            return False
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        """Loads all Chapel data into memory when the cog is ready."""
        self.logger.info("Loading CopyChapel data into memory...")
        self.settings_cache = await self.data_manager.get_data("role_settings")
        self.message_map_cache = await self.data_manager.get_data("chapel_message_map")
        self.logger.info("CopyChapel data cache is ready.")

    def _get_config(self, guild_id: int) -> Optional[Dict]:
        """Gets a guild's chapel config from the in-memory cache."""
        config = self.settings_cache.get(str(guild_id), {}).get("chapel_config")
        if config:
            config.setdefault("threshold", 2) # Ensure threshold has a default
        return config

    # --- Event Listeners ---
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent):
        """Your original, proven reaction handling logic, adapted for the new architecture."""
        if not payload.guild_id: 
            return
        
        config = self._get_config(payload.guild_id)
        if not config or str(payload.emoji) != config.get("emote"):
            return

        try:
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return

        if message.author.bot: 
            return

        reaction = discord.utils.get(message.reactions, emoji=str(payload.emoji))
        reaction_count = reaction.count if reaction else 0
        
        if reaction_count >= config.get("threshold", 2):
            await self._post_or_update_chapel_message(message, config, reaction_count)
        else:
            await self._delete_chapel_message(message.guild.id, message.id)
            
    # --- Refactored Admin Command ---
    @app_commands.command(name="chapel-admin", description="[Admin] Configure the message-copying chapel.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        action="The action to perform.", 
        channel="The channel for copied messages.", 
        emote="The trigger emote.", 
        threshold="Reactions needed."
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Configure", value="configure"), 
        app_commands.Choice(name="View Status", value="status"), 
        app_commands.Choice(name="Reset", value="reset")
    ])
    async def chapel_admin(self, interaction: discord.Interaction, action: str, 
                          channel: Optional[discord.TextChannel] = None, 
                          emote: Optional[str] = None, 
                          threshold: Optional[app_commands.Range[int, 1, 100]] = None):
        if not await self._is_feature_enabled(interaction): return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        
        if action == "configure":
            if not all([channel, emote, threshold]):
                return await interaction.followup.send("To configure, you must provide `channel`, `emote`, and `threshold`.")
            
            # Validate emote (from newer version's logic)
            emote = emote.strip()
            match = re.match(r'<a?:([a-zA-Z0-9_]+):([0-9]+)>', emote)
            if match:
                # It's a custom emoji
                emoji_id = int(match.group(2))
                found_emote = self.bot.get_emoji(emoji_id)
                if not found_emote or found_emote.guild.id != interaction.guild.id:
                    return await interaction.followup.send(self.personality.get("invalid_emote", "That doesn't look like a valid custom emote from this server."))
                emote_str = str(found_emote)
            else:
                # Assume it's a unicode emoji
                emote_str = emote
            
            guild_settings = self.settings_cache.setdefault(guild_id, {})
            guild_settings["chapel_config"] = {
                "channel_id": channel.id, 
                "emote": emote_str, 
                "threshold": threshold
            }
            await self.data_manager.save_data("role_settings", self.settings_cache)
            await interaction.followup.send(f"Done. Chapel is now configured for {channel.mention} with {emote_str} and a threshold of **{threshold}**.")

        elif action == "status":
            config = self._get_config(interaction.guild_id)
            if not config: 
                return await interaction.followup.send(self.personality.get("config_not_found", "Chapel is not configured for this server."))
            
            chapel_channel = self.bot.get_channel(config.get("channel_id", 0))
            embed = discord.Embed(title="Chapel Configuration Status", color=discord.Color.blue())
            embed.add_field(name="Channel", value=chapel_channel.mention if chapel_channel else "Not Found", inline=False)
            embed.add_field(name="Trigger Emote", value=config.get("emote", "Not Set"), inline=False)
            embed.add_field(name="Reaction Threshold", value=str(config.get("threshold", "Not Set")), inline=False)
            await interaction.followup.send(embed=embed)
        
        elif action == "reset":
            if self.settings_cache.get(guild_id, {}).pop("chapel_config", None):
                await self.data_manager.save_data("role_settings", self.settings_cache)
                await interaction.followup.send(self.personality.get("config_reset", "Chapel configuration has been reset."))
            else:
                await interaction.followup.send(self.personality.get("config_not_found", "Chapel is not configured for this server."))

    # --- Helper Methods ---
    async def _post_or_update_chapel_message(self, message: discord.Message, config: dict, count: int):
        guild_id, message_id = str(message.guild.id), str(message.id)
        chapel_channel = self.bot.get_channel(config["channel_id"])
        if not chapel_channel: 
            return
        
        guild_message_map = self.message_map_cache.setdefault(guild_id, {})
        embed = self._create_chapel_embed(message, config["emote"], count)
        
        try:
            if message_id in guild_message_map:
                chapel_message = await chapel_channel.fetch_message(guild_message_map[message_id])
                await chapel_message.edit(embed=embed)
            else:
                chapel_message = await chapel_channel.send(embed=embed)
                guild_message_map[message_id] = chapel_message.id
                await self.data_manager.save_data("chapel_message_map", self.message_map_cache)
        except (discord.NotFound, discord.Forbidden) as e:
            self.logger.warning(f"Failed to post/update chapel message: {e}")
            if isinstance(e, discord.NotFound):
                guild_message_map.pop(message_id, None)
                await self.data_manager.save_data("chapel_message_map", self.message_map_cache)

    async def _delete_chapel_message(self, guild_id: int, message_id: int):
        guild_id_str, message_id_str = str(guild_id), str(message_id)
        config = self._get_config(guild_id)
        guild_message_map = self.message_map_cache.get(guild_id_str, {})
        if not config or message_id_str not in guild_message_map: 
            return
        chapel_channel = self.bot.get_channel(config["channel_id"])
        if not chapel_channel: 
            return
        try:
            chapel_message = await chapel_channel.fetch_message(guild_message_map[message_id_str])
            await chapel_message.delete()
        except (discord.NotFound, discord.Forbidden): 
            pass
        finally:
            guild_message_map.pop(message_id_str, None)
            await self.data_manager.save_data("chapel_message_map", self.message_map_cache)

    # --- EMBED LOGIC ---
    def _create_chapel_embed(self, message: discord.Message, emoji: str, count: int) -> discord.Embed:
        embed = discord.Embed(color=0x5865F2, timestamp=message.created_at)
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)

        description_parts, image_url = [], None
        
        # Logic to find the primary image, checking both the message and its reply
        if message.attachments and (att := message.attachments[0]).content_type and att.content_type.startswith("image/"):
            image_url = att.url
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            replied_to = message.reference.resolved
            if replied_to.content:
                description_parts.append(f"> {replied_to.content[:70]}{'...' if len(replied_to.content) > 70 else ''}")
            if not image_url and replied_to.attachments and (r_att := replied_to.attachments[0]).content_type and r_att.content_type.startswith("image/"):
                image_url = r_att.url
        if message.content:
            description_parts.append(message.content)
        
        embed.description = "\n".join(description_parts) or discord.Embed.Empty
        if image_url:
            embed.set_image(url=image_url)

        embed.add_field(
            name="\u200b", # Zero-width space
            value=f"[#{message.channel.name}]({message.jump_url}) | {emoji} {count}"
        )
        return embed

async def setup(bot):
    await bot.add_cog(CopyChapel(bot))