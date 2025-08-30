# --- plugins/community/chapel_plugin.py ---

import discord
from discord import app_commands
from discord.ext import commands # <-- IMPORT ADDED
import re

from plugins.base_plugin import BasePlugin
from shared.utils.decorators import is_bot_admin

class ChapelPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "chapel"

    # --- Event Listeners for Reactions ---
    @commands.Cog.listener() # <-- DECORATOR CORRECTED (lowercase 'c')
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # We only care about reactions in guilds
        if not payload.guild_id:
            return

        config = await self.db.get_guild_data(payload.guild_id, self.name)
        chapel_settings = config.get("settings")
        if not chapel_settings or not chapel_settings.get("enabled", False):
            return

        # Check if the reaction emoji is the one we're looking for
        if str(payload.emoji) != chapel_settings.get("emote"):
            return

        try:
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return # Can't access the message, so we can't process it

        # Ignore reactions from bots or on bot messages
        if message.author.bot:
            return

        # Find the specific reaction on the message to get its count
        reaction = discord.utils.get(message.reactions, emoji=payload.emoji)
        if not reaction:
            return

        # Check if the count meets the threshold
        threshold = chapel_settings.get("threshold", 3)
        if reaction.count >= threshold:
            await self._post_to_chapel(message, reaction.count, config, chapel_settings)

    async def _post_to_chapel(self, message: discord.Message, count: int, config: dict, settings: dict):
        """Finds or creates a chapel post and updates it."""
        chapel_channel_id = settings.get("channel_id")
        if not chapel_channel_id: return

        chapel_channel = self.bot.get_channel(chapel_channel_id)
        if not chapel_channel: return

        message_map = config.setdefault("message_map", {})
        existing_post_id = message_map.get(str(message.id))

        # Create the embed for the chapel post
        embed = discord.Embed(
            description=message.content,
            color=0xFEE75C, # Gold
            timestamp=message.created_at
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="Source", value=f"[Jump to Message]({message.jump_url})")
        embed.set_footer(text=f"{settings.get('emote')} {count} | in #{message.channel.name}")
        
        if message.attachments and message.attachments[0].content_type.startswith("image/"):
            embed.set_image(url=message.attachments[0].url)

        try:
            if existing_post_id:
                chapel_message = await chapel_channel.fetch_message(existing_post_id)
                await chapel_message.edit(embed=embed)
            else:
                chapel_message = await chapel_channel.send(embed=embed)
                message_map[str(message.id)] = chapel_message.id
                await self.db.save_guild_data(message.guild.id, self.name, config)
        except (discord.NotFound, discord.Forbidden) as e:
            self.logger.warning(f"Failed to post to chapel channel: {e}")
            if existing_post_id:
                message_map.pop(str(message.id), None)
                await self.db.save_guild_data(message.guild.id, self.name, config)

    # --- Admin Commands ---
    chapel_group = app_commands.Group(name="chapel", description="Manage the server's chapel (starboard).")

    @chapel_group.command(name="setup", description="[Admin] Set up the chapel channel, emote, and threshold.")
    @app_commands.describe(
        channel="The channel where popular messages will be posted.",
        emote="The emoji that will trigger the chapel.",
        threshold="How many reactions are needed to post."
    )
    @is_bot_admin()
    async def setup_chapel(self, interaction: discord.Interaction, channel: discord.TextChannel, emote: str, threshold: app_commands.Range[int, 1, 100]):
        config = await self.db.get_guild_data(interaction.guild.id, self.name)
        config["settings"] = {
            "enabled": True,
            "channel_id": channel.id,
            "emote": emote,
            "threshold": threshold
        }
        await self.db.save_guild_data(interaction.guild.id, self.name, config)
        await interaction.response.send_message(
            f"Chapel has been set up!\n"
            f"- Channel: {channel.mention}\n"
            f"- Emote: {emote}\n"
            f"- Threshold: **{threshold}**",
            ephemeral=True
        )