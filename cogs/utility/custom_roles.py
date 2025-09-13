# cogs/utility/custom_roles.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import asyncio
import time
from typing import Dict, Optional

# Imports from our new project structure
from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin
from utils.frustration_manager import get_frustration_level

class CustomRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["custom_roles"]
        self.data_manager = self.bot.data_manager

        # --- OPTIMIZATION: Caching for role positions ---
        # The original code already had a good caching system for this, which we will keep.
        self._position_lock = asyncio.Lock()
        self._guild_cache: Dict[str, Dict] = {}
        self._cache_ttl = 300  # Cache guild settings for 5 minutes
        self._last_cache_update: Dict[str, float] = {}

    # --- User Commands ---
    role_group = app_commands.Group(name="role", description="Commands for managing your personal custom role.")

    @role_group.command(name="set", description="Create or update your custom role.")
    @app_commands.describe(name="The name for your role.", color="The color in hex format (e.g., #FF5733).")
    async def set_role(self, interaction: discord.Interaction, name: str, color: str):
        await interaction.response.defer(ephemeral=True)

        if not self._validate_role_name(name):
            return await interaction.followup.send(self.personality["invalid_name"])
        discord_color = self._hex_to_discord_color(color)
        if discord_color is None:
            return await interaction.followup.send(self.personality["invalid_color"])
            
        guild_data = await self._get_cached_guild_data(interaction.guild)
        if not guild_data.get("can_manage_roles"):
            return await interaction.followup.send("I'm missing the 'Manage Roles' permission.")
        if not guild_data.get("target_roles"):
            return await interaction.followup.send("An admin needs to set a target role first using `/role-admin set-target`.")

        user_roles_data = await self.data_manager.get_data("user_roles")
        guild_id, user_id = str(interaction.guild.id), str(interaction.user.id)
        user_roles = user_roles_data.setdefault(guild_id, {})
        
        existing_role_id = user_roles.get(user_id, {}).get("role_id")
        existing_role = interaction.guild.get_role(existing_role_id) if existing_role_id else None

        try:
            if existing_role:
                await existing_role.edit(name=name, color=discord_color, reason=f"Updated by {interaction.user.display_name}")
                role_to_update = existing_role
            else:
                role_to_update = await interaction.guild.create_role(name=name, color=discord_color, reason=f"Created by {interaction.user.display_name}")
                await interaction.user.add_roles(role_to_update)

            await self._position_role(role_to_update, interaction.guild)
            user_roles[user_id] = {"role_id": role_to_update.id}
            await self.data_manager.save_data("user_roles", user_roles_data)

            frustration = get_frustration_level(self.bot, interaction)
            response_index = min(frustration, len(self.personality["set_responses"]) - 1)
            await interaction.followup.send(self.personality["set_responses"][response_index])

        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to do that. My role is probably too low.")
        except Exception as e:
            self.logger.error("Error in /role set", exc_info=e)
            await interaction.followup.send("Something went wrong on my end. Sorry.")

    @role_group.command(name="view", description="View your current custom role.")
    async def view_role(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        role = await self._get_user_role(interaction.user)
        if not role:
            return await interaction.followup.send(self.personality["no_role"])
        embed = discord.Embed(title=self.personality["role_view"], description=f"Here is your **{role.name}** role.", color=role.color)
        embed.add_field(name="Color", value=f"`{str(role.color).upper()}`"); embed.add_field(name="Position", value=role.position)
        await interaction.followup.send(embed=embed)

    @role_group.command(name="delete", description="Delete your custom role.")
    async def delete_role(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        role = await self._get_user_role(interaction.user)
        if not role:
            return await interaction.followup.send(self.personality["no_role"])
        try:
            await role.delete(reason=f"Deleted by owner {interaction.user.display_name}")
        except discord.Forbidden:
            return await interaction.followup.send("I can't delete that role.")
        
        user_roles_data = await self.data_manager.get_data("user_roles")
        guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
        if user_roles_data.get(guild_id, {}).pop(user_id, None):
            await self.data_manager.save_data("user_roles", user_roles_data)
        await interaction.followup.send(self.personality["role_deleted"])

    # --- Admin Commands ---
    admin_group = app_commands.Group(name="role-admin", description="Admin commands for the custom role system.", default_permissions=discord.Permissions(administrator=True))

    @admin_group.command(name="set-target", description="Set the role that custom roles will be placed above.")
    @is_bot_admin()
    async def set_target(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        if role.position >= interaction.guild.me.top_role.position:
            return await interaction.followup.send(self.personality["target_too_high"])
            
        settings_data = await self.data_manager.get_data("role_settings")
        guild_id = str(interaction.guild_id)
        settings_data.setdefault(guild_id, {})["target_role_ids"] = [role.id] # Simplified to one role for now
        await self.data_manager.save_data("role_settings", settings_data)
        
        # Invalidate the cache for this guild
        self._guild_cache.pop(f"guild_{guild_id}", None)
        await interaction.followup.send(self.personality["target_set"])

    @admin_group.command(name="cleanup", description="Clean up data for roles that no longer exist.")
    @is_bot_admin()
    async def cleanup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        user_roles_data = await self.data_manager.get_data("user_roles")
        guild_roles = user_roles_data.get(guild_id, {})
        
        if not guild_roles:
            return await interaction.followup.send(self.personality["admin_no_cleanup"])
        
        to_remove = [uid for uid, data in guild_roles.items() if not interaction.guild.get_role(data.get("role_id"))]
        if not to_remove:
            return await interaction.followup.send(self.personality["admin_no_cleanup"])
            
        for user_id in to_remove:
            del guild_roles[user_id]
        
        await self.data_manager.save_data("user_roles", user_roles_data)
        await interaction.followup.send(self.personality["admin_cleanup"].format(count=len(to_remove)))

    # --- Helper & Logic Methods ---
    async def _get_user_role(self, user: discord.Member) -> Optional[discord.Role]:
        user_roles_data = await self.data_manager.get_data("user_roles")
        role_id = user_roles_data.get(str(user.guild.id), {}).get(str(user.id), {}).get("role_id")
        return user.guild.get_role(role_id) if role_id else None

    def _validate_role_name(self, name: str) -> bool:
        name = name.strip()
        if not (1 < len(name) <= 100): return False
        if re.search(r'[@#`\\*_~|]', name): return False
        return True

    def _hex_to_discord_color(self, hex_color: str) -> Optional[discord.Color]:
        hex_color = hex_color.strip().lstrip('#')
        if len(hex_color) == 3: hex_color = ''.join([c*2 for c in hex_color])
        if not re.match(r"^[0-9A-Fa-f]{6}$", hex_color): return None
        try: return discord.Color(int(hex_color, 16))
        except ValueError: return None

    async def _get_cached_guild_data(self, guild: discord.Guild) -> Dict:
        cache_key = f"guild_{guild.id}"
        now = time.time()
        if cache_key in self._guild_cache and now - self._last_cache_update.get(cache_key, 0) < self._cache_ttl:
            return self._guild_cache[cache_key]

        settings_data = await self.data_manager.get_data("role_settings")
        target_ids = settings_data.get(str(guild.id), {}).get("target_role_ids", [])
        target_roles = sorted([r for r in [guild.get_role(rid) for rid in target_ids] if r], key=lambda r: r.position, reverse=True)
        
        cache_data = {
            "can_manage_roles": guild.me.guild_permissions.manage_roles,
            "bot_top_role_pos": guild.me.top_role.position,
            "target_roles": target_roles
        }
        self._guild_cache[cache_key] = cache_data
        self._last_cache_update[cache_key] = now
        return cache_data

    async def _position_role(self, role: discord.Role, guild: discord.Guild):
        async with self._position_lock:
            try:
                guild_data = await self._get_cached_guild_data(guild)
                if not guild_data["can_manage_roles"] or not guild_data["target_roles"]:
                    return

                highest_target_pos = guild_data["target_roles"][0].position
                desired_position = min(guild_data["bot_top_role_pos"] - 1, highest_target_pos + 1)
                
                if role.position != desired_position:
                    await role.edit(position=desired_position, reason="Positioning custom role")
            except Exception as e:
                self.logger.error(f"Failed to position role {role.id}", exc_info=e)

async def setup(bot):
    await bot.add_cog(CustomRoles(bot))