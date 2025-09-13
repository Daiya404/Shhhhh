# cogs/utility/custom_roles.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import asyncio
import time
from typing import Dict, Optional, List

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin
from utils.frustration_manager import get_frustration_level

class CustomRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["custom_roles"]
        self.data_manager = self.bot.data_manager
        self._position_lock = asyncio.Lock()
        self._guild_cache: Dict[str, Dict] = {}
        self._cache_ttl = 300
        self._last_cache_update: Dict[str, float] = {}

    # --- User-Facing Commands ---

    @app_commands.command(name="personal-role", description="Create or update your personal custom role.")
    @app_commands.describe(name="The name for your role.", color="The color in hex format (e.g., #A020F0).")
    async def personal_role(self, interaction: discord.Interaction, name: str, color: str):
        await interaction.response.defer(ephemeral=True)

        if not self._validate_role_name(name):
            return await interaction.followup.send(self.personality["invalid_name"])
        discord_color = self._hex_to_discord_color(color)
        if discord_color is None:
            return await interaction.followup.send(self.personality["invalid_color"])
            
        guild_data = await self._get_cached_guild_data(interaction.guild)
        if not guild_data.get("can_manage_roles"):
            return await interaction.followup.send("I'm missing the 'Manage Roles' permission.")
        if not guild_data.get("target_role"):
            return await interaction.followup.send("An admin needs to set a target role first using `/custom-roles-admin`.")

        user_roles_data = await self.data_manager.get_data("user_roles")
        guild_id, user_id = str(interaction.guild.id), str(interaction.user.id)
        user_roles = user_roles_data.setdefault(guild_id, {})
        
        existing_role_id = user_roles.get(user_id, {}).get("role_id")
        existing_role = interaction.guild.get_role(existing_role_id) if existing_role_id else None

        try:
            role_to_update = existing_role or await interaction.guild.create_role(name=name, reason=f"Created by {interaction.user.display_name}")
            await role_to_update.edit(name=name, color=discord_color)
            if not existing_role: await interaction.user.add_roles(role_to_update)

            await self._position_role(role_to_update, interaction.guild)
            user_roles[user_id] = {"role_id": role_to_update.id}
            await self.data_manager.save_data("user_roles", user_roles_data)

            frustration = get_frustration_level(self.bot, interaction)
            response_index = min(frustration, len(self.personality["set_responses"]) - 1)
            await interaction.followup.send(self.personality["set_responses"][response_index])

        except discord.Forbidden:
            await interaction.followup.send("I can't do that. My role is probably too low.")
        except Exception as e:
            self.logger.error("Error in /personal-role", exc_info=e)
            await interaction.followup.send("Something went wrong on my end. Sorry.")

    @app_commands.command(name="custom-roles-list", description="View your custom role or another user's.")
    @app_commands.describe(user="The user whose role you want to view (optional).")
    async def custom_roles_list(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target_user = user or interaction.user
        await interaction.response.defer(ephemeral=True)
        role = await self._get_user_role(target_user)
        if not role:
            return await interaction.followup.send(f"{target_user.display_name} doesn't have a custom role.")
        
        embed = discord.Embed(
            title=f"Custom Role for {target_user.display_name}",
            description=f"Here are the details for the **{role.name}** role.",
            color=role.color
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        embed.add_field(name="Color", value=f"`{str(role.color).upper()}`")
        embed.add_field(name="Position", value=role.position)
        await interaction.followup.send(embed=embed)

    # --- Admin Command ---
    @app_commands.command(name="custom-roles-admin", description="[Admin] Configure the custom role system.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        action="The administrative action to perform.",
        role="The target role to place personal roles above (for 'set-target')."
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Set Target Role", value="set-target"),
        app_commands.Choice(name="Cleanup Orphaned Roles", value="cleanup"),
    ])
    async def custom_roles_admin(self, interaction: discord.Interaction, action: str, role: Optional[discord.Role] = None):
        await interaction.response.defer(ephemeral=True)

        # --- Set Target Logic ---
        if action == "set-target":
            if not role:
                return await interaction.followup.send("You must provide a `role` to set as the target.")
            if role.position >= interaction.guild.me.top_role.position:
                return await interaction.followup.send(self.personality["target_too_high"])
            
            settings_data = await self.data_manager.get_data("role_settings")
            guild_id = str(interaction.guild.id)
            settings_data.setdefault(guild_id, {})["target_role_id"] = role.id # Now singular
            await self.data_manager.save_data("role_settings", settings_data)
            
            self._guild_cache.pop(f"guild_{guild_id}", None) # Invalidate cache
            await interaction.followup.send(self.personality["target_set"])

        # --- Cleanup Logic ---
        elif action == "cleanup":
            guild_id = str(interaction.guild.id)
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

    # --- Helper & Logic Methods (Optimized) ---
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
        target_id = settings_data.get(str(guild.id), {}).get("target_role_id")
        target_role = guild.get_role(target_id) if target_id else None
        
        cache_data = {
            "can_manage_roles": guild.me.guild_permissions.manage_roles,
            "bot_top_role_pos": guild.me.top_role.position,
            "target_role": target_role # Now singular
        }
        self._guild_cache[cache_key] = cache_data
        self._last_cache_update[cache_key] = now
        return cache_data

    async def _position_role(self, role: discord.Role, guild: discord.Guild):
        async with self._position_lock:
            try:
                guild_data = await self._get_cached_guild_data(guild)
                if not guild_data["can_manage_roles"] or not guild_data["target_role"]:
                    return

                target_pos = guild_data["target_role"].position
                desired_position = min(guild_data["bot_top_role_pos"] - 1, target_pos + 1)
                
                if role.position != desired_position:
                    await role.edit(position=desired_position, reason="Positioning custom role")
            except Exception as e:
                self.logger.error(f"Failed to position role {role.id}", exc_info=e)

async def setup(bot):
    await bot.add_cog(CustomRoles(bot))