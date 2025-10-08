# cogs/moderation/copy_chapel.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import asyncio
from typing import Dict, Optional, Union

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

class CopyChapel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["copy_chapel"]
        self.data_manager = self.bot.data_manager

        # --- OPTIMIZATIONS ---
        self.settings_cache: Dict[str, Dict] = {}
        self.message_map_cache: Dict[str, Dict[str, int]] = {}
        
        # Background saving mechanism to reduce I/O load
        self.save_lock = asyncio.Lock()
        self.is_dirty = asyncio.Event() # Event to signal when a save is needed
        self.save_task: Optional[asyncio.Task] = None

    # --- COG LIFECYCLE (SETUP & SHUTDOWN) ---
    async def cog_load(self):
        """Called when the cog is loaded. Starts the background saving task."""
        self.logger.info("Loading CopyChapel data into memory...")
        self.settings_cache = await self.data_manager.get_data("role_settings")
        self.message_map_cache = await self.data_manager.get_data("chapel_message_map")
        self.save_task = self.bot.loop.create_task(self._periodic_save())
        self.logger.info("CopyChapel data cache is ready.")

    async def cog_unload(self):
        """Called when the cog is unloaded. Cancels the task and performs a final save."""
        if self.save_task:
            self.save_task.cancel()
        
        # Perform one final save to ensure no data is lost
        if self.is_dirty.is_set():
            self.logger.info("Performing final save for CopyChapel data...")
            async with self.save_lock:
                await self.data_manager.save_data("chapel_message_map", self.message_map_cache)
            self.logger.info("Final save complete.")

    async def _periodic_save(self):
        """A background task that saves the message map to disk periodically."""
        while not self.bot.is_closed():
            try:
                # Wait until the is_dirty event is set
                await self.is_dirty.wait()
                
                # Wait for a quiet period before saving to batch multiple quick changes
                await asyncio.sleep(60)

                async with self.save_lock:
                    await self.data_manager.save_data("chapel_message_map", self.message_map_cache)
                    self.is_dirty.clear() # Reset the event after saving
                    self.logger.info("Periodically saved chapel message map.")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in periodic save task: {e}", exc_info=True)
                await asyncio.sleep(120) # Wait longer after an error

    def _get_config(self, guild_id: int) -> Optional[Dict]:
        """Gets a guild's chapel config from the in-memory cache."""
        config = self.settings_cache.get(str(guild_id), {}).get("chapel_config")
        if config:
            config.setdefault("threshold", 2)
        return config
    
    async def _is_feature_enabled_interaction(self, interaction: discord.Interaction) -> bool:
        """Helper for checking feature status from an interaction."""
        feature_manager = self.bot.get_cog("FeatureManager")
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, "copy_chapel"):
            await interaction.response.send_message("Hmph. The Copy Chapel feature is disabled on this server.", ephemeral=True)
            return False
        return True

    def _is_feature_enabled_guild(self, guild_id: int) -> bool:
        """Helper for checking feature status from a guild ID."""
        feature_manager = self.bot.get_cog("FeatureManager")
        return feature_manager and feature_manager.is_feature_enabled(guild_id, "copy_chapel")

    # --- Event Listeners ---
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent):
        """Optimized reaction handler."""
        if not self._is_feature_enabled_guild(payload.guild_id):
            return
        
        config = self._get_config(payload.guild_id)
        if not config or str(payload.emoji) != config.get("emote"):
            return

        # Optimization: Don't fetch the message unless we might need to act.
        # We only need the full message object to get the accurate count and content.
        try:
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return

        if message.author.bot: 
            return

        reaction = discord.utils.get(message.reactions, emoji=str(payload.emoji))
        reaction_count = reaction.count if reaction else 0
        
        threshold = config.get("threshold", 2)
        
        if reaction_count >= threshold:
            await self._post_or_update_chapel_message(message, config, reaction_count)
        elif reaction_count < threshold:
            await self._delete_chapel_message(message.guild.id, message.id)
            
    # --- Admin Command ---
    @app_commands.command(name="chapel-admin", description="[Admin] Configure the message-copying chapel.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        action="The action to perform.", 
        channel="The channel or thread for copied messages.", 
        emote="The trigger emote.", 
        threshold="Reactions needed to copy a message."
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Configure", value="configure"), 
        app_commands.Choice(name="View Status", value="status"), 
        app_commands.Choice(name="Reset", value="reset")
    ])
    async def chapel_admin(self, interaction: discord.Interaction, action: str, 
                          channel: Optional[Union[discord.TextChannel, discord.Thread]] = None, 
                          emote: Optional[str] = None, 
                          threshold: Optional[app_commands.Range[int, 1, 100]] = None):
        if not await self._is_feature_enabled_interaction(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        
        if action == "configure":
            if not all([channel, emote, threshold]):
                return await interaction.followup.send("To configure, you must provide `channel`, `emote`, and `threshold`.")
            
            # Check bot permissions in the target channel/thread
            perms = channel.permissions_for(interaction.guild.me)
            if not perms.send_messages or not perms.embed_links:
                return await interaction.followup.send(f"I'm missing permissions in {channel.mention}. I need `Send Messages` and `Embed Links`.")

            # Validate emote
            emote = emote.strip()
            match = re.match(r'<a?:([a-zA-Z0-9_]+):([0-9]+)>', emote)
            if match and (found_emote := self.bot.get_emoji(int(match.group(2)))):
                if found_emote.guild.id != interaction.guild.id:
                    return await interaction.followup.send(self.personality.get("invalid_emote", "That emote is not from this server."))
                emote_str = str(found_emote)
            else:
                emote_str = emote # Assume unicode
            
            guild_settings = self.settings_cache.setdefault(guild_id, {})
            guild_settings["chapel_config"] = {"channel_id": channel.id, "emote": emote_str, "threshold": threshold}
            await self.data_manager.save_data("role_settings", self.settings_cache)
            await interaction.followup.send(f"Done. Chapel is now configured for {channel.mention} with {emote_str} and a threshold of **{threshold}**.")

        elif action == "status":
            config = self._get_config(interaction.guild_id)
            if not config: 
                return await interaction.followup.send(self.personality.get("config_not_found", "Chapel is not configured."))
            
            chapel_channel = self.bot.get_channel(config.get("channel_id", 0))
            embed = discord.Embed(title="Chapel Configuration Status", color=discord.Color.blue())
            embed.add_field(name="Channel / Thread", value=chapel_channel.mention if chapel_channel else "Not Found", inline=False)
            embed.add_field(name="Trigger Emote", value=config.get("emote", "Not Set"), inline=False)
            embed.add_field(name="Reaction Threshold", value=str(config.get("threshold", "Not Set")), inline=False)
            await interaction.followup.send(embed=embed)
        
        elif action == "reset":
            if self.settings_cache.get(guild_id, {}).pop("chapel_config", None):
                await self.data_manager.save_data("role_settings", self.settings_cache)
                await interaction.followup.send(self.personality.get("config_reset", "Chapel configuration has been reset."))
            else:
                await interaction.followup.send(self.personality.get("config_not_found", "Chapel is not configured."))

    # --- Helper Methods ---
    async def _post_or_update_chapel_message(self, message: discord.Message, config: dict, count: int):
        guild_id, message_id = str(message.guild.id), str(message.id)
        chapel_channel = self.bot.get_channel(config["channel_id"])
        if not chapel_channel: return
        
        guild_message_map = self.message_map_cache.setdefault(guild_id, {})
        embed = self._create_chapel_embed(message, config["emote"], count)
        
        try:
            if message_id in guild_message_map:
                chapel_message = await chapel_channel.fetch_message(guild_message_map[message_id])
                await chapel_message.edit(embed=embed)
            else:
                chapel_message = await chapel_channel.send(embed=embed)
                guild_message_map[message_id] = chapel_message.id
                self.is_dirty.set() # Signal that a save is needed
        except (discord.NotFound, discord.Forbidden) as e:
            self.logger.warning(f"Failed to post/update chapel message: {e}")
            if isinstance(e, discord.NotFound) and message_id in guild_message_map:
                del guild_message_map[message_id]
                self.is_dirty.set()

    async def _delete_chapel_message(self, guild_id: int, message_id: int):
        guild_id_str, message_id_str = str(guild_id), str(message_id)
        config = self._get_config(guild_id)
        guild_message_map = self.message_map_cache.get(guild_id_str, {})
        
        if not config or message_id_str not in guild_message_map: return
        
        chapel_channel = self.bot.get_channel(config["channel_id"])
        if not chapel_channel: return
        
        try:
            chapel_message = await chapel_channel.fetch_message(guild_message_map[message_id_str])
            await chapel_message.delete()
        except (discord.NotFound, discord.Forbidden): pass
        finally:
            if guild_message_map.pop(message_id_str, None):
                self.is_dirty.set() # Signal that a save is needed

    def _create_chapel_embed(self, message: discord.Message, emoji: str, count: int) -> discord.Embed:
        # This function remains unchanged, as it's already robust.
        embed = discord.Embed(color=0x5865F2, timestamp=message.created_at)
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        description_parts, image_url = [], None
        if message.attachments and (att := message.attachments[0]).content_type and att.content_type.startswith("image/"):
            image_url = att.url
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            replied_to = message.reference.resolved
            if replied_to.content: description_parts.append(f"> {replied_to.content[:70]}{'...' if len(replied_to.content) > 70 else ''}")
            if not image_url and replied_to.attachments and (r_att := replied_to.attachments[0]).content_type and r_att.content_type.startswith("image/"):
                image_url = r_att.url
        if message.content: description_parts.append(message.content)
        embed.description = "\n".join(description_parts) or discord.Embed.Empty
        if image_url: embed.set_image(url=image_url)
        embed.add_field(name="\u200b", value=f"[#{message.channel.name}]({message.jump_url}) | {emoji} {count}")
        return embed

async def setup(bot):
    await bot.add_cog(CopyChapel(bot))