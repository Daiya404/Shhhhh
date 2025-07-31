import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
import re
import asyncio
import time
from typing import Dict, List, Optional

# Import our custom checks and utilities
from .bot_admin import BotAdmin
from utils.frustration_manager import get_frustration_level

# --- Self-Contained Personality for this Cog ---
PERSONALITY = {
    "set_responses": [
        "There, your role is set. Don't mess it up.",
        "Changed it again? Fine. It's updated.",
        "Are you sure about this one? Whatever, it's done.",
        "Okay, this is the last time I'm changing it for a bit. Your role is updated. Now stop."
    ],
    "role_view": "You want to admire the role I made for you? Here are the details.",
    "role_deleted": "Done. Your custom role has been deleted.",
    "no_role": "You don't even have a custom role. Use `/role set` to make one first.",
    "invalid_name": "That's a terrible name for a role. It has invalid characters or is too long. Pick something better.",
    "invalid_color": "That's not a color. Use a real hex code, like `#A020F0`.",
    "target_set": "Understood. I'll now place all new custom roles above the ones you specified.",
    "target_too_high": "I can't place roles above that one. It's higher than my own role. Pick something below me.",
    "admin_cleanup": "Cleanup complete. Removed `{count}` orphaned role entries.",
    "admin_no_cleanup": "I checked. There was nothing to clean up. Everything is already perfect, as expected."
}

class CustomRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.settings_file = Path("data/role_settings.json")
        self.user_roles_file = Path("data/user_roles.json")

        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        self.user_roles_data: Dict[str, Dict] = self._load_json(self.user_roles_file)

        # Optimizations
        self._save_lock = asyncio.Lock()
        self._position_lock = asyncio.Lock()
        self._guild_cache: Dict[str, Dict] = {}
        self._cache_ttl = 300
        self._last_cache_update: Dict[str, float] = {}

    def _load_json(self, file_path: Path) -> Dict:
        if not file_path.exists(): return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            self.logger.error(f"Error loading {file_path}", exc_info=True)
            return {}

    async def _save_json(self, data: dict, file_path: Path):
        async with self._save_lock:
            try:
                temp_file = file_path.with_suffix(".tmp")
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                temp_file.replace(file_path)
            except Exception as e:
                self.logger.error(f"Error saving {file_path}", exc_info=True)

    # --- User Command Group ---
    role_group = app_commands.Group(name="role", description="Commands for managing your personal custom role.")

    @role_group.command(name="set", description="Create or update your custom role.")
    @app_commands.describe(name="The name for your role.", color="The color in hex format (e.g., #FF5733).")
    async def set_role(self, interaction: discord.Interaction, name: str, color: str):
        await interaction.response.defer(ephemeral=True)

        if not self._validate_role_name(name):
            return await interaction.followup.send(PERSONALITY["invalid_name"], ephemeral=True)
        discord_color = self._hex_to_discord_color(color)
        if discord_color is None:
            return await interaction.followup.send(PERSONALITY["invalid_color"], ephemeral=True)
            
        guild = interaction.guild
        user = interaction.user
        guild_id, user_id = str(guild.id), str(user.id)

        guild_data = await self._get_cached_guild_data(guild)
        if not guild_data.get("can_manage_roles"):
            return await interaction.followup.send("I'm missing the 'Manage Roles' permission.", ephemeral=True)
        if not guild_data.get("target_roles"):
            return await interaction.followup.send("An admin needs to set a target role first using `/role-admin set-target`.", ephemeral=True)

        self.user_roles_data.setdefault(guild_id, {})
        existing_role_data = self.user_roles_data[guild_id].get(user_id)
        existing_role = guild.get_role(existing_role_data["role_id"]) if existing_role_data else None

        try:
            role_to_update = existing_role or await guild.create_role(name=name, reason=f"Created by {user.display_name}")
            await role_to_update.edit(name=name, color=discord_color)
            if not existing_role: await user.add_roles(role_to_update)

            await self._position_role(role_to_update, guild)
            self.user_roles_data[guild_id][user_id] = {"role_id": role_to_update.id}
            await self._save_json(self.user_roles_data, self.user_roles_file)

            frustration = get_frustration_level(self.bot, interaction)
            response_index = min(frustration, len(PERSONALITY["set_responses"]) - 1)
            await interaction.followup.send(PERSONALITY["set_responses"][response_index], ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to do that. My role is probably too low.", ephemeral=True)
        except Exception as e:
            self.logger.error("Error in /role set", exc_info=e)
            await interaction.followup.send("Something went wrong on my end. Sorry.", ephemeral=True)
    
    @role_group.command(name="view", description="View your current custom role.")
    async def view_role(self, interaction: discord.Interaction):
        role = await self._get_user_role(interaction.user)
        if not role:
            return await interaction.response.send_message(PERSONALITY["no_role"], ephemeral=True)
            
        embed = discord.Embed(
            title=PERSONALITY["role_view"],
            description=f"Here is your **{role.name}** role.",
            color=role.color
        )
        embed.add_field(name="Color", value=f"`{str(role.color).upper()}`")
        embed.add_field(name="Position", value=role.position)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @role_group.command(name="delete", description="Delete your custom role.")
    async def delete_role(self, interaction: discord.Interaction):
        role = await self._get_user_role(interaction.user)
        if not role:
            return await interaction.response.send_message(PERSONALITY["no_role"], ephemeral=True)
            
        try: await role.delete(reason=f"Deleted by owner {interaction.user.display_name}")
        except discord.Forbidden: return await interaction.response.send_message("I can't delete that role.", ephemeral=True)
        
        guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
        if self.user_roles_data.get(guild_id, {}).get(user_id):
            del self.user_roles_data[guild_id][user_id]
            await self._save_json(self.user_roles_data, self.user_roles_file)
            
        await interaction.response.send_message(PERSONALITY["role_deleted"], ephemeral=True)

    # --- Admin Command Group ---
    admin_group = app_commands.Group(name="role-admin", description="Admin commands for the custom role system.")

    @admin_group.command(name="set-target", description="Set the role(s) that custom roles will be placed above.")
    @app_commands.describe(role1="The primary marker role.", role2="Optional second marker.", role3="Optional third marker.")
    @BotAdmin.is_bot_admin()
    async def set_target(self, interaction: discord.Interaction, role1: discord.Role, role2: discord.Role=None, role3: discord.Role=None):
        target_roles = [r for r in [role1, role2, role3] if r]
        if any(r.position >= interaction.guild.me.top_role.position for r in target_roles):
            return await interaction.response.send_message(PERSONALITY["target_too_high"], ephemeral=True)
            
        guild_id = str(interaction.guild_id)
        self.settings_data.setdefault(guild_id, {})["target_role_ids"] = [r.id for r in target_roles]
        await self._save_json(self.settings_data, self.settings_file)
        
        if f"guild_{guild_id}" in self._guild_cache:
            del self._guild_cache[f"guild_{guild_id}"]

        await interaction.response.send_message(PERSONALITY["target_set"], ephemeral=True)

    @admin_group.command(name="cleanup", description="Clean up data for roles that no longer exist.")
    @BotAdmin.is_bot_admin()
    async def cleanup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        if guild_id not in self.user_roles_data:
            return await interaction.followup.send(PERSONALITY["admin_no_cleanup"], ephemeral=True)
        
        to_remove = [uid for uid, data in self.user_roles_data[guild_id].items() if not interaction.guild.get_role(data["role_id"])]
        if not to_remove:
            return await interaction.followup.send(PERSONALITY["admin_no_cleanup"], ephemeral=True)
            
        for user_id in to_remove: del self.user_roles_data[guild_id][user_id]
        await self._save_json(self.user_roles_data, self.user_roles_file)
        await interaction.followup.send(PERSONALITY["admin_cleanup"].format(count=len(to_remove)), ephemeral=True)

    # --- Core Logic & Helpers ---
    async def _get_user_role(self, user: discord.Member) -> Optional[discord.Role]:
        """A helper to safely get a user's custom role object."""
        role_data = self.user_roles_data.get(str(user.guild.id), {}).get(str(user.id))
        return user.guild.get_role(role_data["role_id"]) if role_data else None

    def _validate_role_name(self, name: str) -> bool:
        name = name.strip()
        if not (1 < len(name) <= 100): return False
        if re.search(r'[@#`\\*_~|]', name): return False
        if re.search(r'\s{2,}', name): return False
        return True

    def _hex_to_discord_color(self, hex_color: str) -> Optional[discord.Color]:
        hex_color = hex_color.strip().lstrip('#')
        if len(hex_color) == 3: hex_color = ''.join([c*2 for c in hex_color])
        if not re.match(r"^[0-9A-Fa-f]{6}$", hex_color): return None
        try: return discord.Color(int(hex_color, 16))
        except (ValueError, OverflowError): return None

    async def _get_cached_guild_data(self, guild: discord.Guild) -> Dict:
        cache_key = f"guild_{guild.id}"
        now = time.time()
        if cache_key in self._guild_cache and now - self._last_cache_update.get(cache_key, 0) < self._cache_ttl:
            return self._guild_cache[cache_key]

        target_ids = self.settings_data.get(str(guild.id), {}).get("target_role_ids", [])
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
        """
        CORRECTED: Uses the more reliable guild.edit_role_positions method.
        """
        async with self._position_lock:
            try:
                guild_data = await self._get_cached_guild_data(guild)
                if not guild_data["can_manage_roles"] or not guild_data["target_roles"]:
                    return

                highest_target_pos = guild_data["target_roles"][0].position
                desired_position = min(guild_data["bot_top_role_pos"] - 1, highest_target_pos + 1)
                
                if role.position != desired_position:
                    # Use a dictionary to specify the new position for the role
                    positions = {role: desired_position}
                    await guild.edit_role_positions(positions, reason="Positioning custom role")
            except Exception as e:
                self.logger.error(f"Failed to position role {role.id}", exc_info=e)

async def setup(bot):
    await bot.add_cog(CustomRoles(bot))