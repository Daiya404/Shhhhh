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
        self.detention_cache: Dict[str, Dict] = {}
        self.settings_cache: Dict[str, Dict] = {}
    
    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """Check if detention system is enabled for this guild."""
        feature_manager = self.bot.get_cog("FeatureManager")
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, "detention_system"):
            await interaction.response.send_message(
                "The detention system is disabled on this server.", 
                ephemeral=True
            )
            return False
        return True

    async def cog_load(self):
        """Load detention data into memory on cog initialization."""
        self.logger.info("Loading detention data...")
        self.detention_cache = await self.data_manager.get_data("detention_data")
        self.settings_cache = await self.data_manager.get_data("role_settings")
        self.logger.info("Detention data loaded.")

    async def is_user_detained(self, message: discord.Message) -> bool:
        """Check if a user is currently in detention."""
        if not message.guild:
            return False
        guild_detentions = self.detention_cache.get(str(message.guild.id), {})
        return str(message.author.id) in guild_detentions

    async def handle_detention_message(self, message: discord.Message):
        """Process messages from detained users."""
        if not message.guild:
            return
            
        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        
        user_data = self.detention_cache.get(guild_id, {}).get(user_id)
        if not user_data:
            return

        # Check if message matches the required sentence
        if message.content.strip() == user_data["sentence"]:
            user_data["reps_remaining"] -= 1
            
            try:
                await message.add_reaction("✅")
            except discord.Forbidden:
                pass
            
            # Check if detention is complete
            if user_data["reps_remaining"] <= 0:
                await self._release_from_detention(message.guild, message.author, completed=True)
            else:
                await self._update_pinned_message(message.guild, message.author)
                await self.data_manager.save_data("detention_data", self.detention_cache)
        else:
            # Wrong message - delete it
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass

    def _get_detention_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        """Get the configured detention role for this guild."""
        guild_id = str(guild.id)
        role_id = self.settings_cache.get(guild_id, {}).get("detention_role_id")
        
        if not role_id:
            return None
        
        return guild.get_role(role_id)

    @app_commands.command(name="detention", description="Manage user detention.")
    @is_bot_admin()
    @app_commands.describe(
        action="Start or release detention",
        user="User to manage",
        sentence="Sentence to type (required for start)",
        repetitions="Number of repetitions (required for start)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Start", value="start"),
        app_commands.Choice(name="Release", value="release")
    ])
    async def detention(
        self, 
        interaction: discord.Interaction, 
        action: str, 
        user: discord.Member,
        sentence: Optional[str] = None,
        repetitions: Optional[app_commands.Range[int, 1, 100]] = None
    ):
        if not await self._is_feature_enabled(interaction):
            return
        
        await interaction.response.defer()

        if action == "start":
            await self._start_detention(interaction, user, sentence, repetitions)
        elif action == "release":
            await self._release_detention(interaction, user)

    async def _start_detention(
        self, 
        interaction: discord.Interaction, 
        user: discord.Member,
        sentence: Optional[str],
        repetitions: Optional[int]
    ):
        """Start a detention session for a user."""
        # Validate inputs
        if not sentence or not repetitions:
            return await interaction.followup.send(
                "Provide both `sentence` and `repetitions`.", 
                ephemeral=True
            )
        
        guild_id = str(interaction.guild.id)
        user_id = str(user.id)
        
        # Check if user is already detained
        if user_id in self.detention_cache.get(guild_id, {}):
            return await interaction.followup.send(
                f"{user.mention} is already in detention.", 
                ephemeral=True
            )
        
        # Check if user is a bot
        if user.bot:
            return await interaction.followup.send(
                "Cannot detain bots.", 
                ephemeral=True
            )
        
        # Check if detention role is configured
        detention_role = self._get_detention_role(interaction.guild)
        if not detention_role:
            return await interaction.followup.send(
                "Detention role not configured. Use `/detention-settings set-role` first.", 
                ephemeral=True
            )
        
        # Get detention channel
        channel_id = self.settings_cache.get(guild_id, {}).get("detention_channel_id")
        if not channel_id:
            return await interaction.followup.send(
                self.personality.get("no_channel_set", "Detention channel not configured. Use `/detention-settings set-channel` first."), 
                ephemeral=True
            )
        
        detention_channel = interaction.guild.get_channel(channel_id)
        if not detention_channel:
            return await interaction.followup.send(
                "Detention channel not found. Please reconfigure it.", 
                ephemeral=True
            )
        
        # Check bot permissions
        bot_member = interaction.guild.get_member(self.bot.user.id)
        if not bot_member.guild_permissions.manage_roles:
            return await interaction.followup.send(
                "I need 'Manage Roles' permission.", 
                ephemeral=True
            )
        
        # Check if user's highest role is manageable
        if user.top_role >= bot_member.top_role:
            return await interaction.followup.send(
                f"Cannot manage {user.mention} - their highest role is too high.", 
                ephemeral=True
            )
        
        # Step 1: Save original roles (excluding @everyone and booster role)
        booster_role_id = self.settings_cache.get(guild_id, {}).get("booster_role_id")
        original_roles = [
            r.id for r in user.roles 
            if not r.is_default() and r.id != booster_role_id
        ]
        self.logger.info(f"[Detention] Saved {len(original_roles)} roles for {user.display_name} (excluded booster role)")
        
        # Step 2: Remove all roles except booster role
        booster_role_id = self.settings_cache.get(guild_id, {}).get("booster_role_id")
        booster_role = interaction.guild.get_role(booster_role_id) if booster_role_id else None
        
        roles_to_keep = [booster_role] if booster_role and booster_role in user.roles else []
        
        try:
            await user.edit(roles=roles_to_keep, reason=f"Detention by {interaction.user.display_name} - removing roles")
            self.logger.info(f"[Detention] Removed all roles from {user.display_name} (kept booster role)")
        except discord.Forbidden:
            return await interaction.followup.send(
                f"Cannot manage roles for {user.mention}.", 
                ephemeral=True
            )
        except discord.HTTPException as e:
            self.logger.error(f"[Detention] Failed to remove roles from {user.display_name}: {e}")
            return await interaction.followup.send(
                f"Failed to manage roles for {user.mention}.", 
                ephemeral=True
            )
        
        # Step 3: Apply the detention role (in addition to booster role if kept)
        roles_to_apply = roles_to_keep + [detention_role]
        try:
            await user.edit(roles=roles_to_apply, reason=f"Detention by {interaction.user.display_name}")
            self.logger.info(f"[Detention] Applied detention role to {user.display_name}")
        except discord.Forbidden:
            # Try to restore original roles if this fails
            self.logger.error(f"[Detention] Failed to apply detention role to {user.display_name}, restoring original roles")
            try:
                restore_roles = [interaction.guild.get_role(rid) for rid in original_roles if interaction.guild.get_role(rid)]
                await user.edit(roles=restore_roles, reason="Detention failed - restoring roles")
            except:
                pass
            return await interaction.followup.send(
                f"Failed to assign detention role to {user.mention}.", 
                ephemeral=True
            )
        except discord.HTTPException as e:
            self.logger.error(f"[Detention] HTTP error applying detention role to {user.display_name}: {e}")
            return await interaction.followup.send(
                f"Failed to assign detention role to {user.mention}.", 
                ephemeral=True
            )
        
        # Create and pin tracking message
        embed = self._create_embed(user, sentence, repetitions, repetitions)
        try:
            pin_message = await detention_channel.send(embed=embed)
            await pin_message.pin()
            pin_message_id = pin_message.id
        except discord.Forbidden:
            self.logger.warning(f"[Detention] Cannot pin message in {detention_channel.name}")
            pin_message = await detention_channel.send(embed=embed)
            pin_message_id = pin_message.id
        except discord.HTTPException as e:
            self.logger.error(f"[Detention] Failed to send pin message: {e}")
            # Continue without pinned message
            pin_message_id = None
        
        # Save to cache
        guild_detentions = self.detention_cache.setdefault(guild_id, {})
        guild_detentions[user_id] = {
            "sentence": sentence,
            "reps_remaining": repetitions,
            "total_reps": repetitions,
            "original_roles": original_roles,
            "pin_message_id": pin_message_id,
            "detained_by_id": interaction.user.id,
            "start_timestamp": int(time.time())
        }
        
        await self.data_manager.save_data("detention_data", self.detention_cache)
        
        await interaction.followup.send(
            self.personality.get("detention_start", f"{user.mention} has been placed in detention in {detention_channel.mention}").format(
                user=user.mention, 
                channel=detention_channel.mention
            )
        )

    async def _release_detention(self, interaction: discord.Interaction, user: discord.Member):
        """Manually release a user from detention."""
        guild_id = str(interaction.guild.id)
        user_id = str(user.id)
        
        if user_id not in self.detention_cache.get(guild_id, {}):
            return await interaction.followup.send(
                self.personality.get("not_detained", f"{user.mention} is not in detention."), 
                ephemeral=True
            )
        
        await self._release_from_detention(interaction.guild, user, completed=False)
        await interaction.followup.send(
            self.personality.get("detention_released", f"{user.mention} has been released from detention.").format(user=user.mention)
        )

    @app_commands.command(name="detention-settings", description="Configure detention system.")
    @is_bot_admin()
    @app_commands.describe(
        action="Configuration action",
        channel="Detention channel (for set-channel)",
        role="Detention role (for set-role)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Set Channel", value="set-channel"),
        app_commands.Choice(name="Set Role", value="set-role"),
        app_commands.Choice(name="Set Booster Role", value="set-booster"),
        app_commands.Choice(name="View Config", value="view"),
        app_commands.Choice(name="List Detained", value="list")
    ])
    async def detention_settings(
        self, 
        interaction: discord.Interaction, 
        action: str,
        channel: Optional[discord.TextChannel] = None,
        role: Optional[discord.Role] = None
    ):
        if not await self._is_feature_enabled(interaction):
            return
        
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild.id)
        
        if action == "set-channel":
            if not channel:
                return await interaction.followup.send("Provide a channel.")
            
            # Check bot permissions in channel
            bot_permissions = channel.permissions_for(interaction.guild.get_member(self.bot.user.id))
            if not bot_permissions.send_messages or not bot_permissions.manage_messages:
                return await interaction.followup.send(
                    f"I need 'Send Messages' and 'Manage Messages' permissions in {channel.mention}."
                )
            
            guild_settings = self.settings_cache.setdefault(guild_id, {})
            guild_settings["detention_channel_id"] = channel.id
            await self.data_manager.save_data("role_settings", self.settings_cache)
            
            await interaction.followup.send(
                self.personality.get("channel_set", f"Detention channel set to {channel.mention}").format(channel=channel.mention)
            )
        
        elif action == "set-role":
            if not role:
                return await interaction.followup.send("Provide a role.")
            
            # Prevent using @everyone or managed roles
            if role.is_default():
                return await interaction.followup.send("Cannot use @everyone as detention role.")
            
            if role.managed:
                return await interaction.followup.send(f"{role.mention} is managed by an integration and cannot be used.")
            
            guild_settings = self.settings_cache.setdefault(guild_id, {})
            guild_settings["detention_role_id"] = role.id
            await self.data_manager.save_data("role_settings", self.settings_cache)
            
            await interaction.followup.send(f"Detention role set to {role.mention}")
        
        elif action == "set-booster":
            if not role:
                return await interaction.followup.send("Provide a role.")
            
            # Prevent using @everyone
            if role.is_default():
                return await interaction.followup.send("Cannot use @everyone as booster role.")
            
            guild_settings = self.settings_cache.setdefault(guild_id, {})
            guild_settings["booster_role_id"] = role.id
            await self.data_manager.save_data("role_settings", self.settings_cache)
            
            await interaction.followup.send(f"Server booster role set to {role.mention}\n*This role will be preserved during detention.*")
        
        elif action == "view":
            guild_settings = self.settings_cache.get(guild_id, {})
            
            channel_id = guild_settings.get("detention_channel_id")
            role_id = guild_settings.get("detention_role_id")
            booster_role_id = guild_settings.get("booster_role_id")
            
            channel_mention = f"<#{channel_id}>" if channel_id else "Not set"
            role_mention = f"<@&{role_id}>" if role_id else "Not set"
            booster_mention = f"<@&{booster_role_id}>" if booster_role_id else "Not set"
            
            # Validate configuration
            warnings = []
            if channel_id and not interaction.guild.get_channel(channel_id):
                warnings.append("⚠️ Configured channel no longer exists")
            if role_id and not interaction.guild.get_role(role_id):
                warnings.append("⚠️ Configured detention role no longer exists")
            if booster_role_id and not interaction.guild.get_role(booster_role_id):
                warnings.append("⚠️ Configured booster role no longer exists")
            
            embed = discord.Embed(
                title="Detention Configuration",
                color=discord.Color.blue()
            )
            embed.add_field(name="Channel", value=channel_mention, inline=False)
            embed.add_field(name="Detention Role", value=role_mention, inline=False)
            embed.add_field(name="Booster Role (Protected)", value=booster_mention, inline=False)
            
            if warnings:
                embed.add_field(name="Warnings", value="\n".join(warnings), inline=False)
            
            await interaction.followup.send(embed=embed)
        
        elif action == "list":
            detained = self.detention_cache.get(guild_id, {})
            if not detained:
                return await interaction.followup.send(
                    self.personality.get("no_one_detained", "No one is currently in detention.")
                )
            
            embed = discord.Embed(
                title="Users in Detention", 
                color=discord.Color.orange()
            )
            
            for user_id_str, data in detained.items():
                member = interaction.guild.get_member(int(user_id_str))
                name = member.display_name if member else f"User {user_id_str}"
                
                detained_by = interaction.guild.get_member(data.get("detained_by_id"))
                detained_by_name = detained_by.display_name if detained_by else "Unknown"
                
                value = (
                    f"**Progress:** {data['total_reps'] - data['reps_remaining']} / {data['total_reps']}\n"
                    f"**Detained by:** {detained_by_name}\n"
                    f"**Started:** <t:{data['start_timestamp']}:R>"
                )
                
                embed.add_field(name=name, value=value, inline=False)
            
            await interaction.followup.send(embed=embed)

    def _create_embed(
        self, 
        user: discord.Member, 
        sentence: str, 
        remaining: int, 
        total: int
    ) -> discord.Embed:
        """Create detention progress embed."""
        embed = discord.Embed(
            title=f"Detention: {user.display_name}",
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(
            name="Sentence",
            value=f"```{sentence}```",
            inline=False
        )
        embed.add_field(
            name="Progress",
            value=f"{total - remaining} / {total} completed",
            inline=False
        )
        return embed

    async def _release_from_detention(self, guild: discord.Guild, user: discord.Member, completed: bool = False):
        """Release a user from detention and restore their roles."""
        guild_id = str(guild.id)
        user_id = str(user.id)
        
        guild_detentions = self.detention_cache.get(guild_id, {})
        user_data = guild_detentions.pop(user_id, None)
        
        if not user_data:
            return
        
        # Delete pinned message
        channel_id = self.settings_cache.get(guild_id, {}).get("detention_channel_id")
        if channel_id and user_data.get("pin_message_id"):
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    msg = await channel.fetch_message(user_data["pin_message_id"])
                    await msg.unpin()
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
        
        # Restore original roles (and keep booster role if they have it)
        booster_role_id = self.settings_cache.get(guild_id, {}).get("booster_role_id")
        booster_role = guild.get_role(booster_role_id) if booster_role_id else None
        
        roles = [guild.get_role(rid) for rid in user_data.get("original_roles", [])]
        roles = [r for r in roles if r is not None]
        
        # Add booster role back if they still have it
        if booster_role and booster_role in user.roles:
            if booster_role not in roles:
                roles.append(booster_role)
        
        try:
            await user.edit(roles=roles, reason="Released from detention")
            self.logger.info(f"[Detention] Restored {len(roles)} roles to {user.display_name}")
        except discord.Forbidden:
            self.logger.error(f"[Detention] Failed to restore roles for {user.display_name}")
        except discord.HTTPException as e:
            self.logger.error(f"[Detention] HTTP error restoring roles for {user.display_name}: {e}")
        
        # Save changes
        await self.data_manager.save_data("detention_data", self.detention_cache)
        
        # Send completion message
        if completed and channel:
            try:
                await channel.send(
                    self.personality.get("detention_done", f"{user.mention} has completed their detention!").format(user=user.mention)
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def _update_pinned_message(self, guild: discord.Guild, user: discord.Member):
        """Update the pinned progress message for a detained user."""
        guild_id = str(guild.id)
        user_id = str(user.id)
        
        data = self.detention_cache.get(guild_id, {}).get(user_id)
        if not data or not data.get("pin_message_id"):
            return
        
        channel_id = self.settings_cache.get(guild_id, {}).get("detention_channel_id")
        if not channel_id:
            return
        
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        
        try:
            msg = await channel.fetch_message(data["pin_message_id"])
            embed = self._create_embed(
                user,
                data["sentence"],
                data["reps_remaining"],
                data["total_reps"]
            )
            await msg.edit(embed=embed)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

async def setup(bot):
    await bot.add_cog(Detention(bot))