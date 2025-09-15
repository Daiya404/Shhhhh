# cogs/admin/detention.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import time
from typing import Optional, Dict

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

class Detention(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["detention"]
        self.data_manager = self.bot.data_manager

        # --- OPTIMIZATION: In-memory caches ---
        self.detention_cache: Dict[str, Dict] = {}
        self.settings_cache: Dict[str, Dict] = {}

    async def cog_load(self):
        """Loads all data into memory when the cog is ready."""
        self.logger.info("Loading Detention data into memory...")
        self.detention_cache = await self.data_manager.get_data("detention_data")
        self.settings_cache = await self.data_manager.get_data("role_settings")
        self.logger.info("Detention data cache is ready.")

    # --- "Traffic Cop" Methods (Operate on Cache) ---
    # --- FIX: Changed from 'def' back to 'async def' to match bot.py's expectation ---
    async def is_user_detained(self, message: discord.Message) -> bool:
        """Optimized: Checks against the in-memory cache."""
        if not message.guild: return False
        guild_detentions = self.detention_cache.get(str(message.guild.id), {})
        return str(message.author.id) in guild_detentions

    async def handle_detention_message(self, message: discord.Message):
        """Optimized: Processes a message from a detained user using the cache."""
        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        
        user_data = self.detention_cache.get(guild_id, {}).get(user_id)
        if not user_data: return

        if message.content.strip() == user_data["sentence"]:
            user_data["reps_remaining"] -= 1
            
            try: await message.add_reaction("✅")
            except discord.Forbidden: pass
            
            if user_data["reps_remaining"] <= 0:
                await self._release_from_detention(message.guild, message.author)
            else:
                await self._update_pinned_message(message.guild, message.author)
        else:
            try: await message.delete()
            except (discord.Forbidden, discord.NotFound): pass

    # --- User Management Command ---
    @app_commands.command(name="detention", description="Place a user in detention or release them.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(action="Start a new detention or release an existing one.", user="The user to manage.", sentence="The sentence to type (required for 'start').", repetitions="How many times to type it (required for 'start').")
    @app_commands.choices(action=[app_commands.Choice(name="Start", value="start"), app_commands.Choice(name="Release", value="release")])
    async def manage_detention(self, interaction: discord.Interaction, action: str, user: discord.Member, sentence: Optional[str] = None, repetitions: Optional[app_commands.Range[int, 1, 100]] = None):
        await interaction.response.defer()

        if action == "start":
            if not sentence or not repetitions:
                return await interaction.followup.send("You need to provide a `sentence` and `repetitions`.", ephemeral=True)
            
            guild_id = str(interaction.guild.id)
            detention_channel_id = self.settings_cache.get(guild_id, {}).get("detention_channel_id")
            if not detention_channel_id or not (detention_channel := interaction.guild.get_channel(detention_channel_id)):
                return await interaction.followup.send(self.personality["no_channel_set"], ephemeral=True)
            
            original_roles = [role.id for role in user.roles if not role.is_default()]
            try:
                detention_role = discord.utils.get(interaction.guild.roles, name="BEHAVE")
                if not detention_role: return await interaction.followup.send(self.personality["missing_role"], ephemeral=True)
                await user.edit(roles=[detention_role], reason=f"Detention by {interaction.user.display_name}")
            except discord.Forbidden:
                return await interaction.followup.send(self.personality["cant_manage_user"].format(user=user.display_name), ephemeral=True)
            
            pin_embed = self._create_pin_embed(user, sentence, repetitions, repetitions)
            pin_message = await detention_channel.send(embed=pin_embed)
            await pin_message.pin()
            
            guild_detentions = self.detention_cache.setdefault(guild_id, {})
            guild_detentions[str(user.id)] = { "sentence": sentence, "reps_remaining": repetitions, "total_reps": repetitions, "original_roles": original_roles, "pin_message_id": pin_message.id, "detained_by_id": interaction.user.id, "start_timestamp": int(time.time()) }
            await self.data_manager.save_data("detention_data", self.detention_cache)
            await interaction.followup.send(self.personality["detention_start"].format(user=user.mention, channel=detention_channel.mention))

        elif action == "release":
            if not self.detention_cache.get(str(interaction.guild.id), {}).get(str(user.id)):
                return await interaction.followup.send(self.personality["not_detained"], ephemeral=True)
            
            await self._release_from_detention(interaction.guild, user)
            await interaction.followup.send(self.personality["detention_released"].format(user=user.mention))

    # --- Configuration Command ---
    @app_commands.command(name="detention-settings", description="Configure the detention channel or list detained users.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(action="Set the channel or list offenders.", channel="The channel to use (required for 'set-channel').")
    @app_commands.choices(action=[app_commands.Choice(name="Set Channel", value="set-channel"), app_commands.Choice(name="List", value="list")])
    async def config_detention(self, interaction: discord.Interaction, action: str, channel: Optional[discord.TextChannel] = None):
        await interaction.response.defer(ephemeral=True)
        
        if action == "set-channel":
            if not channel: return await interaction.followup.send("You must provide a `channel` to set.")

            guild_settings = self.settings_cache.setdefault(str(interaction.guild.id), {})
            guild_settings["detention_channel_id"] = channel.id
            await self.data_manager.save_data("role_settings", self.settings_cache)
            await interaction.followup.send(self.personality["channel_set"].format(channel=channel.mention))

        elif action == "list":
            detained_users = self.detention_cache.get(str(interaction.guild.id), {})
            if not detained_users: return await interaction.followup.send(self.personality["no_one_detained"])

            embed = discord.Embed(title="Users Currently in Detention", color=discord.Color.orange())
            for user_id_str, data in detained_users.items():
                member = interaction.guild.get_member(int(user_id_str))
                name = member.display_name if member else f"User ID: {user_id_str}"
                embed.add_field(name=name, value=f"**Remaining:** {data['reps_remaining']} / {data['total_reps']}", inline=False)
            await interaction.followup.send(embed=embed)

    # --- Helper Methods ---
    def _create_pin_embed(self, user: discord.Member, sentence: str, remaining: int, total: int) -> discord.Embed:
        embed = discord.Embed(title=f"Detention for {user.display_name}", color=discord.Color.red())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Sentence to Type", value=f"```{sentence}```", inline=False)
        embed.add_field(name="Progress", value=f"**{total - remaining} / {total}** completed", inline=False)
        return embed

    async def _release_from_detention(self, guild: discord.Guild, user: discord.Member):
        guild_id, user_id = str(guild.id), str(user.id)
        guild_detentions = self.detention_cache.get(guild_id, {})
        user_data = guild_detentions.pop(user_id, None)
        if user_data is None: return
        
        channel_id = self.settings_cache.get(guild_id, {}).get("detention_channel_id")
        if channel_id and (channel := guild.get_channel(channel_id)):
            try: 
                msg = await channel.fetch_message(user_data["pin_message_id"])
                await msg.unpin()
                await msg.delete()
            except (discord.NotFound, discord.Forbidden): pass
        
        roles_to_restore = [guild.get_role(rid) for rid in user_data.get("original_roles", []) if guild.get_role(rid)]
        try: await user.edit(roles=roles_to_restore, reason="Released from detention.")
        except discord.Forbidden: self.logger.error(f"Failed to restore roles for {user.display_name}.")
        
        await self.data_manager.save_data("detention_data", self.detention_cache)
        
        if user_data.get('reps_remaining', 1) <= 0 and channel:
            await channel.send(self.personality["detention_done"].format(user=user.mention))

    async def _update_pinned_message(self, guild: discord.Guild, user: discord.Member):
        guild_id, user_id = str(guild.id), str(user.id)
        data = self.detention_cache.get(guild_id, {}).get(user_id)
        if not data: return
        
        channel_id = self.settings_cache.get(guild_id, {}).get("detention_channel_id")
        if not channel_id or not (channel := guild.get_channel(channel_id)): return

        try: 
            msg = await channel.fetch_message(data["pin_message_id"])
            new_embed = self._create_pin_embed(user, data["sentence"], data["reps_remaining"], data["total_reps"])
            await msg.edit(embed=new_embed)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException): pass

async def setup(bot):
    await bot.add_cog(Detention(bot))