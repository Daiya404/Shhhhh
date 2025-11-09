# cogs/utility/custom_roles.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
import asyncio
import time
from typing import Dict, Optional, List
from collections import defaultdict

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

# --- UI Views for Admin Cleanup ---
class RoleCleanupSelect(discord.ui.Select):
    def __init__(self, cog, roles_to_clean: List[discord.Role]):
        self.cog = cog
        options = [discord.SelectOption(label=role.name, value=str(role.id), emoji="🗑️") for role in roles_to_clean[:25]]
        super().__init__(placeholder="Select a single orphaned role to delete...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        role_id = int(self.values[0])
        role = interaction.guild.get_role(role_id)
        if role:
            await self.cog._delete_and_untrack_role(role)
            await interaction.followup.send(f"✅ Deleted orphaned role: **{role.name}**", ephemeral=True)
            await self.view.refresh(interaction)

class RoleCleanupView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild, author_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.author_id = author_id
        self.roles_to_clean: List[discord.Role] = []

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id: 
            return True
        await interaction.response.send_message("This is not for you.", ephemeral=True)
        return False

    async def populate_items(self):
        self.clear_items()
        self.roles_to_clean = await self.cog._find_orphaned_roles(self.guild)
        if self.roles_to_clean:
            self.add_item(RoleCleanupSelect(self.cog, self.roles_to_clean))
            self.add_item(self.delete_all_button)

    @discord.ui.button(label="Delete All Shown", style=discord.ButtonStyle.danger, row=1)
    async def delete_all_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"Deleting {len(self.roles_to_clean)} roles...", ephemeral=True)
        deleted_count = 0
        for role in self.roles_to_clean:
            if await self.cog._delete_and_untrack_role(role):
                deleted_count += 1
            await asyncio.sleep(0.5)
        await interaction.edit_original_response(content=f"✅ Cleanup complete. Deleted {deleted_count} orphaned roles.", view=None)
        self.stop()

    async def refresh(self, interaction: discord.Interaction):
        await self.populate_items()
        if not self.roles_to_clean:
            await interaction.edit_original_response(content="✅ All orphaned roles have been cleaned up!", view=None)
            self.stop()
        else:
            await interaction.edit_original_response(view=self)

# --- Main Cog ---
class CustomRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["custom_roles"]
        self.data_manager = self.bot.data_manager
        
        self.roles_cache: Dict[str, Dict[str, int]] = {}
        self.primary_roles_cache: Dict[str, Dict[str, int]] = {}
        self.settings_cache: Dict[str, Dict] = {}
        self._position_lock = asyncio.Lock()

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """A local check to see if the custom_roles feature is enabled."""
        feature_manager = self.bot.get_cog("FeatureManager")
        feature_name = "custom_roles" 
        
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, feature_name):
            await interaction.response.send_message(f"Hmph. The {feature_name.replace('_', ' ').title()} feature is disabled on this server.", ephemeral=True)
            return False
        return True

    async def cog_load(self):
        self.roles_cache = await self.data_manager.get_data("custom_roles_tracking")
        self.primary_roles_cache = await self.data_manager.get_data("user_primary_roles")
        self.settings_cache = await self.data_manager.get_data("role_settings")
        self.logger.info("Custom Roles data caches are ready.")

    async def role_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        guild_roles = self.roles_cache.get(str(interaction.guild.id), {})
        owned_role_ids = [int(rid) for rid, uid in guild_roles.items() if uid == interaction.user.id]
        choices = [
            app_commands.Choice(name=role.name, value=str(role.id)) 
            for rid in owned_role_ids 
            if (role := interaction.guild.get_role(rid)) and current.lower() in role.name.lower()
        ]
        return choices[:25]

    # --- Combined User Command ---
    @app_commands.command(name="personal-role", description="Create or update your personal custom role.")
    @app_commands.describe(
        action="Whether to create a new role or update an existing one",
        name="The name for the role (required for create, optional for update)",
        color="The color in hex format (e.g., #A020F0)",
        primary="Make this your primary role? (sets name color)",
        role="The existing role to update (required for update)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Create New Role", value="create"),
        app_commands.Choice(name="Update Existing Role", value="update")
    ])
    @app_commands.autocomplete(role=role_autocomplete)
    async def personal_role(
        self, 
        interaction: discord.Interaction, 
        action: str,
        name: Optional[str] = None,
        color: Optional[str] = None,
        primary: Optional[bool] = None,
        role: Optional[str] = None
    ):
        if not await self._is_feature_enabled(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        
        if action == "create":
            await self._handle_create_role(interaction, name, color, primary)
        elif action == "update":
            await self._handle_update_role(interaction, role, name, color, primary)

    async def _handle_create_role(self, interaction: discord.Interaction, name: Optional[str], color: Optional[str], primary: Optional[bool]):
        if not name:
            return await interaction.followup.send("❌ Role name is required when creating a new role.")
        
        if not color:
            return await interaction.followup.send("❌ Color is required when creating a new role.")
        
        if not self._validate_role_name(name):
            return await interaction.followup.send(self.personality["invalid_name"])
        
        discord_color = self._hex_to_discord_color(color)
        if discord_color is None:
            return await interaction.followup.send(self.personality["invalid_color"])

        # Get current target role based on CURRENT permissions
        member = await interaction.guild.fetch_member(interaction.user.id)
        target_role = await self._get_current_target_role(member)
        if not target_role:
            return await interaction.followup.send("❌ An admin needs to set a target role first.")

        try:
            new_role = await interaction.guild.create_role(
                name=name, 
                color=discord_color, 
                reason=f"Tika Custom Role by {interaction.user}"
            )
            await member.add_roles(new_role)
            
            guild_id_str = str(interaction.guild.id)
            self.roles_cache.setdefault(guild_id_str, {})[str(new_role.id)] = interaction.user.id
            
            # Default primary to True if not specified
            is_primary = primary if primary is not None else True
            
            if is_primary:
                await self._set_primary_role(interaction.user, new_role, target_role)
            else:
                await self._position_role_below_target(new_role, target_role)

            await self._save_all_data()
            await interaction.followup.send(self.personality["set_responses"][0])
        except discord.Forbidden:
            await interaction.followup.send("❌ I can't do that. My role is probably too low.")
        except Exception as e:
            self.logger.error("Error in personal-role create", exc_info=e)
            await interaction.followup.send("❌ Something went wrong.")

    async def _handle_update_role(self, interaction: discord.Interaction, role: Optional[str], name: Optional[str], color: Optional[str], primary: Optional[bool]):
        if not role:
            return await interaction.followup.send("❌ You must select a role to update.")
        
        try:
            role_obj = interaction.guild.get_role(int(role))
            if not role_obj:
                raise ValueError("Role not found")
        except (ValueError, TypeError):
            return await interaction.followup.send("❌ Invalid role selected or role no longer exists.")
        
        if self.roles_cache.get(str(interaction.guild.id), {}).get(str(role_obj.id)) != interaction.user.id:
            return await interaction.followup.send("❌ Hmph. That's not your role to edit.")

        edit_kwargs, changes = {}, []
        
        if name:
            if not self._validate_role_name(name):
                return await interaction.followup.send(self.personality["invalid_name"])
            edit_kwargs["name"] = name
            changes.append(f"name to **{name}**")

        if color:
            discord_color = self._hex_to_discord_color(color)
            if discord_color is None:
                return await interaction.followup.send(self.personality["invalid_color"])
            edit_kwargs["color"] = discord_color
            changes.append(f"color to `{color}`")

        try:
            old_name = role_obj.name
            if edit_kwargs:
                await role_obj.edit(**edit_kwargs)
            
            if primary is not None:
                # Get current target role based on CURRENT permissions
                member = await interaction.guild.fetch_member(interaction.user.id)
                target_role = await self._get_current_target_role(member)
                if not target_role:
                    return await interaction.followup.send("❌ Target role not set.")
                
                if primary:
                    await self._set_primary_role(interaction.user, role_obj, target_role)
                    changes.append("set as primary")
                else:
                    await self._position_role_below_target(role_obj, target_role)
                    changes.append("unset as primary")

            if not changes:
                return await interaction.followup.send("❌ You didn't specify anything to change.")
            
            await interaction.followup.send(f"✅ Updated role **{old_name}**: " + ", ".join(changes) + ".")
        except discord.Forbidden:
            await interaction.followup.send("❌ I can't do that. My role is probably too low.")
        except Exception as e:
            self.logger.error("Error in personal-role update", exc_info=e)
            await interaction.followup.send("❌ Something went wrong.")

    # --- Combined Admin Command ---
    @app_commands.command(name="custom-roles-admin", description="[Admin] Manage the custom role system.")
    @app_commands.describe(
        action="What admin action to perform",
        target_type="For set-target: Is this for regular users or admins?",
        role="The role to use (for set-target or register)",
        user="The user who owns the role (for register only)"
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Set Target Role", value="set-target"),
            app_commands.Choice(name="View Configuration", value="view-config"),
            app_commands.Choice(name="View All Roles", value="view-all"),
            app_commands.Choice(name="Register Existing Role", value="register"),
            app_commands.Choice(name="Cleanup Orphaned Roles", value="cleanup")
        ],
        target_type=[
            app_commands.Choice(name="Regular Users", value="user"),
            app_commands.Choice(name="Administrators", value="admin")
        ]
    )
    @is_bot_admin()
    async def custom_roles_admin(
        self,
        interaction: discord.Interaction,
        action: str,
        target_type: Optional[str] = None,
        role: Optional[discord.Role] = None,
        user: Optional[discord.Member] = None
    ):
        if not await self._is_feature_enabled(interaction):
            return
        if action == "set-target":
            await self._handle_set_target(interaction, target_type, role)
        elif action == "view-config":
            await self._handle_view_config(interaction)
        elif action == "register":
            await self._handle_register_role(interaction, role, user)
        elif action == "cleanup":
            await self._handle_cleanup(interaction)
        elif action == "view-all":
            await self._handle_view_all_roles(interaction)

    async def _handle_set_target(self, interaction: discord.Interaction, target_type: Optional[str], role: Optional[discord.Role]):
        if not target_type or not role:
            return await interaction.response.send_message("❌ Both target type and role are required for set-target.", ephemeral=True)
        
        guild_settings = self.settings_cache.setdefault(str(interaction.guild.id), {})
        key = "admin_target_role_id" if target_type == "admin" else "user_target_role_id"
        guild_settings[key] = role.id
        await self.data_manager.save_data("role_settings", self.settings_cache)
        await interaction.response.send_message(f"✅ Set **{role.name}** as the target for **{target_type}** roles.", ephemeral=True)

    async def _handle_view_config(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_settings = self.settings_cache.get(str(interaction.guild.id), {})
        admin_id = guild_settings.get("admin_target_role_id")
        user_id = guild_settings.get("user_target_role_id")
        admin_role = interaction.guild.get_role(admin_id) if admin_id else None
        user_role = interaction.guild.get_role(user_id) if user_id else None
        total = len(self.roles_cache.get(str(interaction.guild.id), {}))
        
        embed = discord.Embed(title="Custom Roles Configuration", color=discord.Color.blue())
        embed.add_field(name="Admin Target", value=admin_role.mention if admin_role else "Not Set", inline=True)
        embed.add_field(name="User Target", value=user_role.mention if user_role else "Not Set", inline=True)
        embed.add_field(name="Tracked Roles", value=f"{total} total", inline=True)
        
        await interaction.followup.send(embed=embed)

    async def _handle_register_role(self, interaction: discord.Interaction, role: Optional[discord.Role], user: Optional[discord.Member]):
        await interaction.response.defer(ephemeral=True)
        if not role or not user:
            return await interaction.followup.send("❌ Both role and user are required for register.")
        
        guild_id_str = str(interaction.guild.id)
        role_id_str = str(role.id)
        guild_roles = self.roles_cache.setdefault(guild_id_str, {})
        
        if role_id_str in guild_roles:
            return await interaction.followup.send("❌ That role is already tracked.")
        
        guild_roles[role_id_str] = user.id
        await self.data_manager.save_data("custom_roles_tracking", self.roles_cache)
        await interaction.followup.send(f"✅ Registered **{role.name}** to {user.mention}.")

    async def _handle_cleanup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = RoleCleanupView(self, interaction.guild, interaction.user.id)
        await view.populate_items()
        
        if not view.roles_to_clean:
            return await interaction.followup.send("✅ No orphaned custom roles to clean up.")
        
        await interaction.followup.send(
            f"Found **{len(view.roles_to_clean)}** tracked roles with 0 members:",
            view=view,
            ephemeral=True
        )

    async def _handle_view_all_roles(self, interaction: discord.Interaction):
        """Generates and sends a list of all tracked roles, grouped by user."""
        await interaction.response.defer(ephemeral=False)
        guild_id_str = str(interaction.guild.id)
        
        guild_roles = self.roles_cache.get(guild_id_str, {})
        primary_roles = self.primary_roles_cache.get(guild_id_str, {})

        if not guild_roles:
            return await interaction.followup.send("There are no tracked custom roles on this server.")

        # Invert primary_roles for quick lookup: {user_id: role_id}
        user_primary_map = {str(uid): pid for str_uid, pid in primary_roles.items() for uid in [int(str_uid)]}

        # Group roles by user
        user_roles_map = defaultdict(lambda: {'primary': None, 'others': []})

        for role_id_str, user_id in guild_roles.items():
            role = interaction.guild.get_role(int(role_id_str))
            if not role:
                continue

            user_id_str = str(user_id)
            if user_primary_map.get(user_id_str) == role.id:
                user_roles_map[user_id]['primary'] = role
            else:
                user_roles_map[user_id]['others'].append(role)

        # Build the description string
        description_lines = []
        sorted_user_ids = sorted(user_roles_map.keys(), key=lambda uid: (interaction.guild.get_member(uid).display_name if interaction.guild.get_member(uid) else str(uid)).lower())

        for user_id in sorted_user_ids:
            user = interaction.guild.get_member(user_id)
            user_mention = user.mention if user else f"<@{user_id}> (User Left)"
            
            description_lines.append(f"**{user_mention}**:")
            
            roles_data = user_roles_map[user_id]
            primary_role = roles_data['primary']
            other_roles = sorted(roles_data['others'], key=lambda r: r.name)

            if primary_role:
                description_lines.append(f"  - **Primary:** {primary_role.mention}")
            
            if other_roles:
                other_mentions = ', '.join(r.mention for r in other_roles)
                description_lines.append(f"  - **Others:** {other_mentions}")
            
            description_lines.append("")

        if not description_lines:
             return await interaction.followup.send("No tracked custom roles were found on this server.")

        embed = discord.Embed(
            title=f"All Tracked Custom Roles ({len(guild_roles)} total)",
            description="\n".join(description_lines),
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed)

    # --- Helper & Logic Methods ---
    async def _save_all_data(self):
        """Save all cached data to storage."""
        await asyncio.gather(
            self.data_manager.save_data("custom_roles_tracking", self.roles_cache),
            self.data_manager.save_data("user_primary_roles", self.primary_roles_cache)
        )

    async def _get_target_role(self, member: discord.Member) -> Optional[discord.Role]:
        """Get the appropriate target role for a member based on their permissions."""
        settings = self.settings_cache.get(str(member.guild.id), {})
        key = "admin_target_role_id" if member.guild_permissions.administrator else "user_target_role_id"
        role_id = settings.get(key)
        return member.guild.get_role(role_id) if role_id else None

    async def _get_current_target_role(self, member: discord.Member) -> Optional[discord.Role]:
        """Get the target role based on whether user has admin target role assigned."""
        settings = self.settings_cache.get(str(member.guild.id), {})
        admin_target_id = settings.get("admin_target_role_id")
        
        # Check if user has the admin target role
        has_admin_target = admin_target_id and any(role.id == admin_target_id for role in member.roles)
        
        # Use admin target if they have it, otherwise user target
        key = "admin_target_role_id" if has_admin_target else "user_target_role_id"
        role_id = settings.get(key)
        return member.guild.get_role(role_id) if role_id else None

    async def _set_primary_role(self, user: discord.Member, new_primary_role: discord.Role, target_role: discord.Role):
        """Set a role as the user's primary role and position it appropriately."""
        guild_id_str = str(user.guild.id)
        user_id_str = str(user.id)
        user_primaries = self.primary_roles_cache.setdefault(guild_id_str, {})
        
        # Move old primary role down if it exists
        old_primary_id = user_primaries.get(user_id_str)
        if old_primary_id:
            old_primary_role = user.guild.get_role(old_primary_id)
            if old_primary_role:
                await self._position_role_below_target(old_primary_role, target_role)
        
        # Set new primary role and position it
        user_primaries[user_id_str] = new_primary_role.id
        await self._position_role_above_target(new_primary_role, target_role)
        await self.data_manager.save_data("user_primary_roles", self.primary_roles_cache)

    async def _find_orphaned_roles(self, guild: discord.Guild) -> List[discord.Role]:
        """Find tracked roles that have no members."""
        guild_roles_tracked = self.roles_cache.get(str(guild.id), {})
        orphaned = []
        
        for role_id_str in guild_roles_tracked:
            role = guild.get_role(int(role_id_str))
            if role and not role.members:
                orphaned.append(role)
        
        return orphaned

    async def _delete_and_untrack_role(self, role: discord.Role) -> bool:
        """Delete a role and remove it from all tracking."""
        try:
            guild_id_str = str(role.guild.id)
            role_id_str = str(role.id)
            
            await role.delete(reason="Tika Custom Role Cleanup")
            
            # Remove from roles cache
            if guild_id_str in self.roles_cache and role_id_str in self.roles_cache[guild_id_str]:
                del self.roles_cache[guild_id_str][role_id_str]
            
            # Remove from primary roles cache
            if guild_id_str in self.primary_roles_cache:
                for user_id, primary_id in list(self.primary_roles_cache[guild_id_str].items()):
                    if primary_id == role.id:
                        del self.primary_roles_cache[guild_id_str][user_id]
                        break
            
            await self._save_all_data()
            return True
        except (discord.Forbidden, discord.HTTPException) as e:
            self.logger.error(f"Failed to delete role {role.name}: {e}")
            return False

    def _validate_role_name(self, name: str) -> bool:
        """Validate that a role name meets Discord's requirements."""
        cleaned_name = name.strip()
        return (
            1 < len(cleaned_name) <= 100 and
            not re.search(r'[@#`\\*_~|]', cleaned_name)
        )

    def _hex_to_discord_color(self, hex_color: str) -> Optional[discord.Color]:
        """Convert a hex color string to a Discord Color object."""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return None
        
        try:
            return discord.Color(int(hex_color, 16))
        except ValueError:
            return None

    async def _position_role_safely(self, role: discord.Role, target_pos: int) -> bool:
        """Safely position a role with retry logic and rate limiting."""
        if role.position == target_pos:
            return True
        
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                async with self._position_lock:
                    await role.edit(position=target_pos, reason="Positioning Tika Custom Role")
                    await asyncio.sleep(0.5)
                    
                    # Verify the position was actually set
                    fresh_role = role.guild.get_role(role.id)
                    if fresh_role and fresh_role.position == target_pos:
                        return True
                        
            except (discord.Forbidden, discord.HTTPException) as e:
                self.logger.warning(f"Failed to position {role.name} on attempt {attempt+1}: {e}")
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                else:
                    return False
        
        return False

    async def _position_role_above_target(self, role: discord.Role, target_role: discord.Role) -> bool:
        """Position a role above the target role, respecting bot permissions."""
        bot_top_pos = role.guild.me.top_role.position
        safe_pos = min(target_role.position + 1, bot_top_pos - 1)
        return await self._position_role_safely(role, safe_pos)

    async def _position_role_below_target(self, role: discord.Role, target_role: discord.Role) -> bool:
        """Position a role below the target role."""
        safe_pos = max(target_role.position, 1)
        return await self._position_role_safely(role, safe_pos)

async def setup(bot):
    await bot.add_cog(CustomRoles(bot))