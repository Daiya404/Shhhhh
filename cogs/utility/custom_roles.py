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

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """A local check to see if the custom_roles feature is enabled."""
        feature_manager = self.bot.get_cog("FeatureManager")
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, "custom_roles"):
            await interaction.response.send_message("Hmph. The Custom Roles feature is disabled on this server.", ephemeral=True)
            return False
        return True

    def _is_admin(self, member: discord.Member) -> bool:
        """Check if member is an admin (has administrator permission)."""
        return member.guild_permissions.administrator

    # --- User-Facing Commands ---

    @app_commands.command(name="personal-role", description="Create or update your personal custom role.")
    @app_commands.describe(
        name="The name for your role.",
        color="The color in hex format (e.g., #A020F0).",
        primary="Whether this should be your primary role (affects your name color)."
    )
    async def personal_role(
        self, 
        interaction: discord.Interaction, 
        name: str, 
        color: str, 
        primary: bool = True
    ):
        if not await self._is_feature_enabled(interaction): 
            return
        await interaction.response.defer(ephemeral=True)

        if not self._validate_role_name(name):
            return await interaction.followup.send(self.personality["invalid_name"])
        
        discord_color = self._hex_to_discord_color(color)
        if discord_color is None:
            return await interaction.followup.send(self.personality["invalid_color"])
            
        guild_data = await self._get_cached_guild_data(interaction.guild)
        if not guild_data.get("can_manage_roles"):
            return await interaction.followup.send("I'm missing the 'Manage Roles' permission.")
        
        # Determine which target role to use based on admin status
        is_admin = self._is_admin(interaction.user)
        target_role = guild_data.get("admin_target_role") if is_admin else guild_data.get("user_target_role")
        
        if not target_role:
            target_type = "admin" if is_admin else "user"
            return await interaction.followup.send(f"An admin needs to set a {target_type} target role first using `/custom-roles-admin`.")

        user_roles_data = await self.data_manager.get_data("user_roles")
        guild_id, user_id = str(interaction.guild.id), str(interaction.user.id)
        user_data = user_roles_data.setdefault(guild_id, {}).setdefault(user_id, {"roles": [], "primary_role": None})
        
        # Check if role with this name already exists for user
        existing_role = None
        for role_info in user_data["roles"]:
            role = interaction.guild.get_role(role_info["role_id"])
            if role and role.name.lower() == name.lower():
                existing_role = role
                break

        try:
            if existing_role:
                # Update existing role
                await existing_role.edit(name=name, color=discord_color)
                role_to_use = existing_role
                
                # Update role info in data
                for role_info in user_data["roles"]:
                    if role_info["role_id"] == existing_role.id:
                        role_info["name"] = name
                        role_info["color"] = str(discord_color).upper()
                        break
            else:
                # Create new role
                role_to_use = await interaction.guild.create_role(
                    name=name, 
                    color=discord_color,
                    reason=f"Custom role created by {interaction.user.display_name} via TikaBot"
                )
                await interaction.user.add_roles(role_to_use)
                
                # Add to user's role list with metadata
                role_info = {
                    "role_id": role_to_use.id,
                    "name": name,
                    "color": str(discord_color).upper(),
                    "created_at": int(time.time()),
                    "created_by": interaction.user.id,
                    "bot_managed": True  # Flag to identify our managed roles
                }
                user_data["roles"].append(role_info)

            # Handle primary role logic with better error handling
            positioning_success = True
            
            if primary:
                # If setting as primary, move old primary role down first
                old_primary_id = user_data.get("primary_role")
                if old_primary_id and old_primary_id != role_to_use.id:
                    old_primary_role = interaction.guild.get_role(old_primary_id)
                    if old_primary_role:
                        # Move old primary role below target
                        old_success = await self._position_role_below_target(old_primary_role, target_role)
                        if not old_success:
                            self.logger.warning(f"Failed to reposition old primary role {old_primary_role.name}")
                
                user_data["primary_role"] = role_to_use.id
                # Position new primary role above target
                positioning_success = await self._position_role_above_target(role_to_use, target_role)
            else:
                # Position non-primary role below target
                positioning_success = await self._position_role_below_target(role_to_use, target_role)
                
                # If this is the user's first role, make it primary automatically
                if not user_data.get("primary_role"):
                    user_data["primary_role"] = role_to_use.id
                    positioning_success = await self._position_role_above_target(role_to_use, target_role)

            await self.data_manager.save_data("user_roles", user_roles_data)

            frustration = get_frustration_level(self.bot, interaction)
            response_index = min(frustration, len(self.personality["set_responses"]) - 1)
            
            is_primary_role = user_data.get("primary_role") == role_to_use.id
            primary_text = " (Primary)" if is_primary_role else ""
            
            # Add positioning warning if needed
            position_warning = ""
            if not positioning_success:
                position_warning = "\n⚠️ Note: Role positioning may not be optimal due to hierarchy constraints."
            
            await interaction.followup.send(
                f"{self.personality['set_responses'][response_index]}{primary_text}{position_warning}"
            )

        except discord.Forbidden:
            await interaction.followup.send("I can't do that. My role is probably too low.")
        except Exception as e:
            self.logger.error("Error in /personal-role", exc_info=e)
            await interaction.followup.send("Something went wrong on my end. Sorry.")

    @app_commands.command(name="role-list", description="View your custom roles or another user's.")
    @app_commands.describe(user="The user whose roles you want to view (optional).")
    async def role_list(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if not await self._is_feature_enabled(interaction): 
            return
        
        target_user = user or interaction.user
        await interaction.response.defer(ephemeral=True)
        
        user_roles_data = await self.data_manager.get_data("user_roles")
        guild_id = str(interaction.guild.id)
        user_data = user_roles_data.get(guild_id, {}).get(str(target_user.id), {"roles": [], "primary_role": None})
        
        if not user_data["roles"]:
            return await interaction.followup.send(f"{target_user.display_name} doesn't have any custom roles.")
        
        embed = discord.Embed(
            title=f"Custom Roles for {target_user.display_name}",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        primary_role_id = user_data.get("primary_role")
        role_list = []
        
        for role_info in user_data["roles"]:
            role = interaction.guild.get_role(role_info["role_id"])
            if role:
                is_primary = role.id == primary_role_id
                primary_marker = " ⭐ **PRIMARY**" if is_primary else ""
                role_list.append(f"**{role.name}** - `{role_info['color']}`{primary_marker}")
        
        if role_list:
            embed.description = "\n".join(role_list)
            if primary_role_id:
                primary_role = interaction.guild.get_role(primary_role_id)
                if primary_role:
                    embed.color = primary_role.color
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="role-delete", description="Delete one of your custom roles.")
    @app_commands.describe(name="The name of the role to delete.")
    async def role_delete(self, interaction: discord.Interaction, name: str):
        if not await self._is_feature_enabled(interaction): 
            return
        await interaction.response.defer(ephemeral=True)

        user_roles_data = await self.data_manager.get_data("user_roles")
        guild_id, user_id = str(interaction.guild.id), str(interaction.user.id)
        user_data = user_roles_data.get(guild_id, {}).get(user_id, {"roles": [], "primary_role": None})
        
        # Find the role to delete
        role_to_delete = None
        role_info_to_remove = None
        
        for role_info in user_data["roles"]:
            role = interaction.guild.get_role(role_info["role_id"])
            if role and role.name.lower() == name.lower():
                role_to_delete = role
                role_info_to_remove = role_info
                break
        
        if not role_to_delete:
            return await interaction.followup.send(f"You don't have a custom role named '{name}'.")
        
        try:
            # Remove role from user and delete it
            await interaction.user.remove_roles(role_to_delete)
            await role_to_delete.delete(reason=f"Custom role deleted by {interaction.user.display_name}")
            
            # Remove from data
            user_data["roles"].remove(role_info_to_remove)
            
            # If this was the primary role, handle primary role reassignment
            if user_data.get("primary_role") == role_to_delete.id:
                user_data["primary_role"] = None
                # Set another role as primary if available
                if user_data["roles"]:  # Check after removal
                    new_primary_role_info = user_data["roles"][0]
                    new_primary_role = interaction.guild.get_role(new_primary_role_info["role_id"])
                    if new_primary_role:
                        user_data["primary_role"] = new_primary_role.id
                        
                        # Position the new primary role correctly
                        guild_data = await self._get_cached_guild_data(interaction.guild)
                        is_admin = self._is_admin(interaction.user)
                        target_pos_role = guild_data.get("admin_target_role") if is_admin else guild_data.get("user_target_role")
                        
                        if target_pos_role:
                            await self._position_role_above_target(new_primary_role, target_pos_role)
            
            await self.data_manager.save_data("user_roles", user_roles_data)
            await interaction.followup.send(f"Deleted your custom role: **{name}**")
            
        except discord.Forbidden:
            await interaction.followup.send("I can't delete that role. My role is probably too low.")
        except Exception as e:
            self.logger.error("Error in /role-delete", exc_info=e)
            await interaction.followup.send("Something went wrong on my end. Sorry.")

    @app_commands.command(name="role-primary", description="Set which of your roles should be primary (affects name color).")
    @app_commands.describe(name="The name of the role to make primary.")
    async def role_primary(self, interaction: discord.Interaction, name: str):
        if not await self._is_feature_enabled(interaction): 
            return
        await interaction.response.defer(ephemeral=True)

        user_roles_data = await self.data_manager.get_data("user_roles")
        guild_id, user_id = str(interaction.guild.id), str(interaction.user.id)
        user_data = user_roles_data.get(guild_id, {}).get(user_id, {"roles": [], "primary_role": None})
        
        # Find the role
        target_role = None
        for role_info in user_data["roles"]:
            role = interaction.guild.get_role(role_info["role_id"])
            if role and role.name.lower() == name.lower():
                target_role = role
                break
        
        if not target_role:
            return await interaction.followup.send(f"You don't have a custom role named '{name}'.")
        
        if user_data.get("primary_role") == target_role.id:
            return await interaction.followup.send(f"**{name}** is already your primary role.")
        
        try:
            guild_data = await self._get_cached_guild_data(interaction.guild)
            is_admin = self._is_admin(interaction.user)
            target_pos_role = guild_data.get("admin_target_role") if is_admin else guild_data.get("user_target_role")
            
            if not target_pos_role:
                return await interaction.followup.send("Target role not configured. Cannot change primary role.")
            
            # Move old primary role down if it exists
            old_primary_id = user_data.get("primary_role")
            if old_primary_id and old_primary_id != target_role.id:
                old_primary_role = interaction.guild.get_role(old_primary_id)
                if old_primary_role:
                    old_success = await self._position_role_below_target(old_primary_role, target_pos_role)
                    if not old_success:
                        self.logger.warning(f"Failed to reposition old primary role {old_primary_role.name}")
            
            # Move new primary role up
            new_success = await self._position_role_above_target(target_role, target_pos_role)
            
            user_data["primary_role"] = target_role.id
            await self.data_manager.save_data("user_roles", user_roles_data)
            
            position_warning = ""
            if not new_success:
                position_warning = "\n⚠️ Note: Role positioning may not be optimal due to hierarchy constraints."
            
            await interaction.followup.send(f"**{name}** is now your primary role!{position_warning}")
            
        except Exception as e:
            self.logger.error("Error in /role-primary", exc_info=e)
            await interaction.followup.send("Something went wrong on my end. Sorry.")

    # --- Admin Commands ---
    @app_commands.command(name="custom-roles-admin", description="[Admin] Configure the custom role system.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        action="The administrative action to perform.",
        role="The target role for positioning.",
        target_type="Whether this target is for admins or regular users."
    )
    @app_commands.choices(
    action=[
        app_commands.Choice(name="Set Target Role", value="set-target"),
        app_commands.Choice(name="View Config", value="view-config"),
        app_commands.Choice(name="Cleanup Orphaned Roles", value="cleanup"),
        app_commands.Choice(name="Register Role", value="register-role"),  # Add this
        app_commands.Choice(name="Fix Positions", value="fix-positions"),   # Add this
        app_commands.Choice(name="Diagnose", value="diagnose"),             # Add this
    ],
        target_type=[
            app_commands.Choice(name="Regular Users", value="user"),
            app_commands.Choice(name="Administrators", value="admin"),
        ]
    )
    async def custom_roles_admin(
        self, 
        interaction: discord.Interaction, 
        action: str, 
        role: Optional[discord.Role] = None,
        target_type: Optional[str] = None
    ):
        if not await self._is_feature_enabled(interaction): 
            return
        await interaction.response.defer(ephemeral=True)

        settings_data = await self.data_manager.get_data("role_settings")
        guild_id = str(interaction.guild.id)
        guild_settings = settings_data.setdefault(guild_id, {})

        # Validate that the admin has permission to set target roles
        if action == "set-target":
            if not role or not target_type:
                return await interaction.followup.send("You must provide both a `role` and `target_type` for set-target.")
            
            # Use the new validation method
            is_valid, error_msg = self._validate_target_role_hierarchy(role, interaction.guild)
            if not is_valid:
                return await interaction.followup.send(f"Invalid target role: {error_msg}")
            
            # Set the appropriate target role
            if target_type == "admin":
                guild_settings["admin_target_role_id"] = role.id
                target_name = "admin"
            else:
                guild_settings["user_target_role_id"] = role.id
                target_name = "user"
            
            await self.data_manager.save_data("role_settings", settings_data)
            self._guild_cache.pop(f"guild_{guild_id}", None)  # Invalidate cache
            
            await interaction.followup.send(f"Set **{role.name}** as the target role for **{target_name}** custom roles.")

        elif action == "view-config":
            embed = discord.Embed(
                title="Custom Roles Configuration",
                color=discord.Color.blue()
            )
            
            admin_target_id = guild_settings.get("admin_target_role_id")
            user_target_id = guild_settings.get("user_target_role_id")
            
            admin_role = interaction.guild.get_role(admin_target_id) if admin_target_id else None
            user_role = interaction.guild.get_role(user_target_id) if user_target_id else None
            
            embed.add_field(
                name="Admin Target Role",
                value=admin_role.mention if admin_role else "Not set",
                inline=True
            )
            embed.add_field(
                name="User Target Role", 
                value=user_role.mention if user_role else "Not set",
                inline=True
            )
            
            # Count active custom roles
            user_roles_data = await self.data_manager.get_data("user_roles")
            guild_roles = user_roles_data.get(guild_id, {})
            total_roles = sum(len(user_data.get("roles", [])) for user_data in guild_roles.values())
            
            embed.add_field(
                name="Active Custom Roles",
                value=str(total_roles),
                inline=True
            )
            
            await interaction.followup.send(embed=embed)

        elif action == "register-role":
            # Manually register an existing role as a custom role for a user
            if not role:
                return await interaction.followup.send("You must specify a role to register.")
            
            # Check if role has exactly one member (typical for personal roles)
            if len(role.members) != 1:
                return await interaction.followup.send(
                    f"Role `{role.name}` has {len(role.members)} members. "
                    f"Personal roles should typically have exactly 1 member."
                )
            
            member = role.members[0]
            user_roles_data = await self.data_manager.get_data("user_roles")
            guild_roles = user_roles_data.setdefault(guild_id, {})
            user_data = guild_roles.setdefault(str(member.id), {"roles": [], "primary_role": None})
            
            # Check if role is already registered
            for role_info in user_data["roles"]:
                if role_info["role_id"] == role.id:
                    return await interaction.followup.send(f"Role `{role.name}` is already registered to {member.display_name}.")
            
            # Register the role
            role_info = {
                "role_id": role.id,
                "name": role.name,
                "color": str(role.color).upper(),
                "created_at": int(time.time()),
                "created_by": member.id,
                "bot_managed": True,
                "manually_registered": True
            }
            user_data["roles"].append(role_info)
            
            # Make it primary if user has no primary role
            if not user_data.get("primary_role"):
                user_data["primary_role"] = role.id
                primary_text = " (set as primary)"
            else:
                primary_text = ""
            
            await self.data_manager.save_data("user_roles", user_roles_data)
            await interaction.followup.send(
                f"Successfully registered `{role.name}` as a custom role for {member.display_name}{primary_text}."
            )

        elif action == "cleanup":
            user_roles_data = await self.data_manager.get_data("user_roles")
            guild_roles = user_roles_data.get(guild_id, {})
            
            if not guild_roles:
                return await interaction.followup.send(self.personality["admin_no_cleanup"])
            
            cleaned_data_count = 0
            deleted_roles_count = 0
            failed_deletions = []
            
            # Collect all role IDs that should exist according to our data
            tracked_role_ids = set()
            for user_data in guild_roles.values():
                for role_info in user_data.get("roles", []):
                    tracked_role_ids.add(role_info["role_id"])
            
            # Check each tracked role
            for user_id, user_data in list(guild_roles.items()):
                if "roles" not in user_data:
                    continue
                
                # Clean up non-existent roles from data
                valid_roles = []
                for role_info in user_data["roles"]:
                    role_id = role_info["role_id"]
                    role = interaction.guild.get_role(role_id)
                    
                    if role:
                        valid_roles.append(role_info)
                    else:
                        # Role doesn't exist anymore - remove from data
                        cleaned_data_count += 1
                        self.logger.info(f"Removed orphaned role data: {role_info.get('name', 'Unknown')} (ID: {role_id})")
                
                user_data["roles"] = valid_roles
                
                # Clean up invalid primary role reference
                primary_id = user_data.get("primary_role")
                if primary_id and not interaction.guild.get_role(primary_id):
                    user_data["primary_role"] = None
                    cleaned_data_count += 1
                    if valid_roles:  # Set first valid role as primary
                        user_data["primary_role"] = valid_roles[0]["role_id"]
                
                # Remove user data if no roles left
                if not valid_roles:
                    del guild_roles[user_id]
            
            # Now find actual Discord roles that are orphaned (exist in guild but not in our data)
            # We'll identify them using multiple methods
            orphaned_discord_roles = []
            
            for role in interaction.guild.roles:
                # Skip system roles and roles above bot
                if role.position >= interaction.guild.me.top_role.position:
                    continue
                if role.is_default() or role.managed:
                    continue
                
                # Skip if role is already tracked
                if role.id in tracked_role_ids:
                    continue
                
                # Method 1: Check if role was created with our reason pattern
                is_bot_created = False
                try:
                    # Check audit logs for role creation
                    async for entry in interaction.guild.audit_logs(
                        action=discord.AuditLogAction.role_create,
                        limit=100
                    ):
                        if entry.target.id == role.id:
                            if "TikaBot" in str(entry.reason) or entry.user == interaction.guild.me:
                                is_bot_created = True
                            break
                except (discord.Forbidden, discord.HTTPException):
                    # Can't access audit logs, fall back to other methods
                    pass
                
                # Method 2: Check if role is positioned like a custom role
                is_near_target = False
                admin_target_id = guild_settings.get("admin_target_role_id")
                user_target_id = guild_settings.get("user_target_role_id")
                admin_target = interaction.guild.get_role(admin_target_id) if admin_target_id else None
                user_target = interaction.guild.get_role(user_target_id) if user_target_id else None
                
                if admin_target and abs(role.position - admin_target.position) <= 3:
                    is_near_target = True
                if user_target and abs(role.position - user_target.position) <= 3:
                    is_near_target = True
                
                # Method 3: Check role characteristics (single user, recent creation, etc.)
                has_custom_characteristics = False
                if (len(role.members) <= 2 and  # Few members
                    not role.permissions.administrator and  # No admin perms
                    not role.mentionable and  # Not mentionable (default for created roles)
                    role.hoist == False):  # Not hoisted (default)
                    has_custom_characteristics = True
                
                # If any method indicates this might be our orphaned role, flag it
                if is_bot_created or (is_near_target and has_custom_characteristics):
                    orphaned_discord_roles.append(role)
            
            # Ask admin if they want to delete the orphaned Discord roles
        if orphaned_discord_roles:
            role_list = "\n".join([f"• {role.name} (ID: {role.id}, Members: {len(role.members)})" 
                                 for role in orphaned_discord_roles[:10]])
            if len(orphaned_discord_roles) > 10:
                role_list += f"\n... and {len(orphaned_discord_roles) - 10} more"
            
            embed = discord.Embed(
                title="⚠️ Orphaned Roles Found",
                description=f"Found {len(orphaned_discord_roles)} roles that appear to be orphaned custom roles:\n\n{role_list}",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="What are orphaned roles?",
                value="These are Discord roles that seem to be custom roles but aren't tracked in my database. This usually happens when:\n• The bot was offline when roles were created\n• Data was corrupted or reset\n• Roles were created manually",
                inline=False
            )
            embed.add_field(
                name="Action Required",
                value="Reply with **yes** to delete these roles, or **no** to cancel (30 second timeout)",
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            
            def msg_check(m):
                return (m.author == interaction.user and 
                        m.channel == interaction.channel and 
                        m.content.lower() in ['yes', 'y', 'no', 'n', 'cancel'])
            
            try:
                response = await self.bot.wait_for('message', timeout=30.0, check=msg_check)
                should_delete = response.content.lower() in ['yes', 'y']
                
                if should_delete:
                    # Delete the orphaned roles
                    for role in orphaned_discord_roles:
                        try:
                            await role.delete(reason="Orphaned custom role cleanup")
                            deleted_roles_count += 1
                            await asyncio.sleep(0.5)  # Rate limit protection
                        except discord.Forbidden:
                            failed_deletions.append(f"{role.name} (insufficient permissions)")
                        except discord.HTTPException as e:
                            failed_deletions.append(f"{role.name} (HTTP error: {e})")
                        except Exception as e:
                            failed_deletions.append(f"{role.name} (error: {e})")
                else:
                    await interaction.followup.send("Cleanup cancelled - no roles were deleted.")
                    
            except asyncio.TimeoutError:
                await interaction.followup.send("Cleanup cancelled due to timeout - no roles were deleted.")
            
            # Save the cleaned data
            await self.data_manager.save_data("user_roles", user_roles_data)
            
            # Prepare final report
            report_parts = []
            if cleaned_data_count > 0:
                report_parts.append(f"Cleaned {cleaned_data_count} orphaned data entries")
            if deleted_roles_count > 0:
                report_parts.append(f"Deleted {deleted_roles_count} orphaned Discord roles")
            if failed_deletions:
                report_parts.append(f"Failed to delete {len(failed_deletions)} roles")
                if len(failed_deletions) <= 5:
                    report_parts.append("Failed roles: " + ", ".join(failed_deletions))
            
            if report_parts:
                final_report = "Cleanup complete!\n " + "\n• ".join(report_parts)
                await interaction.edit_original_response(content=final_report, embed=None, view=None)
            else:
                await interaction.edit_original_response(
                    content=self.personality["admin_no_cleanup"], 
                    embed=None, 
                    view=None
                )

        elif action == "fix-positions":
            # Fix all custom role positions
            user_roles_data = await self.data_manager.get_data("user_roles")
            guild_roles = user_roles_data.get(guild_id, {})
            
            if not guild_roles:
                return await interaction.followup.send("No custom roles to fix.")
            
            admin_target = guild_settings.get("admin_target_role_id")
            user_target = guild_settings.get("user_target_role_id")
            admin_target_role = interaction.guild.get_role(admin_target) if admin_target else None
            user_target_role = interaction.guild.get_role(user_target) if user_target else None
            
            fixed_count = 0
            failed_count = 0
            
            for user_id, user_data in guild_roles.items():
                try:
                    user = interaction.guild.get_member(int(user_id))
                    if not user:
                        continue
                    
                    is_admin = self._is_admin(user)
                    target_role = admin_target_role if is_admin else user_target_role
                    
                    if not target_role:
                        continue
                    
                    primary_id = user_data.get("primary_role")
                    
                    for role_info in user_data.get("roles", []):
                        role = interaction.guild.get_role(role_info["role_id"])
                        if not role:
                            continue
                        
                        if role.id == primary_id:
                            # Fix primary role position
                            success = await self._position_role_above_target(role, target_role)
                        else:
                            # Fix non-primary role position
                            success = await self._position_role_below_target(role, target_role)
                        
                        if success:
                            fixed_count += 1
                        else:
                            failed_count += 1
                        
                        # Small delay to avoid rate limits
                        await asyncio.sleep(0.2)
                        
                except Exception as e:
                    self.logger.error(f"Error fixing positions for user {user_id}: {e}")
                    failed_count += 1
            
            result_msg = f"Position fixing complete. Fixed: {fixed_count}, Failed: {failed_count}"
            await interaction.followup.send(result_msg)

        elif action == "diagnose":
            # Diagnose role hierarchy issues
            embed = discord.Embed(
                title="Role Hierarchy Diagnostics",
                color=discord.Color.orange()
            )
            
            # Bot role info
            bot_role = interaction.guild.me.top_role
            embed.add_field(
                name="Bot's Highest Role",
                value=f"{bot_role.name} (Position: {bot_role.position})",
                inline=False
            )
            
            # Target roles info
            admin_target_id = guild_settings.get("admin_target_role_id")
            user_target_id = guild_settings.get("user_target_role_id")
            admin_target = interaction.guild.get_role(admin_target_id) if admin_target_id else None
            user_target = interaction.guild.get_role(user_target_id) if user_target_id else None
            
            if admin_target:
                valid_admin, admin_msg = self._validate_target_role_hierarchy(admin_target, interaction.guild)
                embed.add_field(
                    name="Admin Target Role",
                    value=f"{admin_target.name} (Pos: {admin_target.position})\n{'✅' if valid_admin else '❌'} {admin_msg}",
                    inline=True
                )
            else:
                embed.add_field(name="Admin Target Role", value="❌ Not configured", inline=True)
            
            if user_target:
                valid_user, user_msg = self._validate_target_role_hierarchy(user_target, interaction.guild)
                embed.add_field(
                    name="User Target Role", 
                    value=f"{user_target.name} (Pos: {user_target.position})\n{'✅' if valid_user else '❌'} {user_msg}",
                    inline=True
                )
            else:
                embed.add_field(name="User Target Role", value="❌ Not configured", inline=True)
            
            # Check for role positioning conflicts
            user_roles_data = await self.data_manager.get_data("user_roles")
            guild_roles = user_roles_data.get(guild_id, {})
            
            misplaced_roles = []
            for user_id, user_data in guild_roles.items():
                try:
                    user = interaction.guild.get_member(int(user_id))
                    if not user:
                        continue
                    
                    is_admin = self._is_admin(user)
                    target_role = admin_target if is_admin else user_target
                    
                    if not target_role:
                        continue
                    
                    primary_id = user_data.get("primary_role")
                    
                    for role_info in user_data.get("roles", []):
                        role = interaction.guild.get_role(role_info["role_id"])
                        if not role:
                            continue
                        
                        is_primary = role.id == primary_id
                        expected_above = is_primary
                        actually_above = role.position > target_role.position
                        
                        if expected_above != actually_above:
                            status = "Should be above target" if expected_above else "Should be below target"
                            misplaced_roles.append(f"{role.name} ({status})")
                
                except Exception as e:
                    self.logger.error(f"Error diagnosing user {user_id}: {e}")
            
            if misplaced_roles:
                embed.add_field(
                    name="⚠️ Misplaced Roles",
                    value="\n".join(misplaced_roles[:10]) + ("\n..." if len(misplaced_roles) > 10 else ""),
                    inline=False
                )
            else:
                embed.add_field(
                    name="✅ Role Positioning",
                    value="All custom roles are correctly positioned",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)

    # --- Helper & Logic Methods ---
    def _validate_role_name(self, name: str) -> bool:
        name = name.strip()
        if not (1 < len(name) <= 100): 
            return False
        if re.search(r'[@#`\\*_~|]', name): 
            return False
        return True

    def _validate_target_role_hierarchy(self, target_role: discord.Role, guild: discord.Guild) -> tuple[bool, str]:
        """Validate that a target role can be used for positioning custom roles."""
        bot_top_position = guild.me.top_role.position
        
        # Target role must be below bot's highest role
        if target_role.position >= bot_top_position:
            return False, "Target role is above or equal to my highest role."
        
        # Target role must be above @everyone (position 0)
        if target_role.position <= 1:
            return False, "Target role is too low - must be above @everyone and have space below."
        
        # Ensure there's space for roles above and below
        if target_role.position >= bot_top_position - 1:
            return False, "Not enough space above target role for primary custom roles."
        
        return True, "Valid target role with proper spacing."

    def _hex_to_discord_color(self, hex_color: str) -> Optional[discord.Color]:
        hex_color = hex_color.strip().lstrip('#')
        if len(hex_color) == 3: 
            hex_color = ''.join([c*2 for c in hex_color])
        if not re.match(r"^[0-9A-Fa-f]{6}$", hex_color): 
            return None
        try: 
            return discord.Color(int(hex_color, 16))
        except ValueError: 
            return None

    async def _migrate_role_data(self, guild_id: str):
        """Migrate existing role data to include bot_managed flag."""
        user_roles_data = await self.data_manager.get_data("user_roles")
        guild_roles = user_roles_data.get(guild_id, {})
        
        needs_migration = False
        for user_data in guild_roles.values():
            for role_info in user_data.get("roles", []):
                if "bot_managed" not in role_info:
                    role_info["bot_managed"] = True  # Assume existing roles are bot-managed
                    needs_migration = True
        
        if needs_migration:
            await self.data_manager.save_data("user_roles", user_roles_data)
            self.logger.info(f"Migrated role data for guild {guild_id}")

    async def _get_cached_guild_data(self, guild: discord.Guild) -> Dict:
        cache_key = f"guild_{guild.id}"
        now = time.time()
        if cache_key in self._guild_cache and now - self._last_cache_update.get(cache_key, 0) < self._cache_ttl:
            return self._guild_cache[cache_key]

        # Ensure data migration on first access
        await self._migrate_role_data(str(guild.id))

        settings_data = await self.data_manager.get_data("role_settings")
        guild_settings = settings_data.get(str(guild.id), {})
        
        admin_target_id = guild_settings.get("admin_target_role_id")
        user_target_id = guild_settings.get("user_target_role_id")
        
        admin_target_role = guild.get_role(admin_target_id) if admin_target_id else None
        user_target_role = guild.get_role(user_target_id) if user_target_id else None
        
        cache_data = {
            "can_manage_roles": guild.me.guild_permissions.manage_roles,
            "bot_top_role_pos": guild.me.top_role.position,
            "admin_target_role": admin_target_role,
            "user_target_role": user_target_role
        }
        self._guild_cache[cache_key] = cache_data
        self._last_cache_update[cache_key] = now
        return cache_data

    async def _get_safe_position_above_target(self, target_role: discord.Role, guild: discord.Guild) -> Optional[int]:
        """Calculate a safe position above the target role."""
        # Get all roles between target and bot's top role
        bot_top_pos = guild.me.top_role.position
        target_pos = target_role.position
        
        # We want to place the role as close as possible above target
        # Start from target + 1 and find the first available spot
        desired_pos = target_pos + 1
        
        # Make sure we don't exceed bot's maximum position
        if desired_pos >= bot_top_pos:
            self.logger.warning(f"Cannot place role above target {target_role.name} - would exceed bot permissions")
            return None
            
        return desired_pos

    async def _get_safe_position_below_target(self, target_role: discord.Role) -> Optional[int]:
        """Calculate a safe position below the target role."""
        target_pos = target_role.position
        
        # Place role immediately below target, but never below position 1
        desired_pos = max(1, target_pos - 1)
        
        if desired_pos < 1:
            self.logger.warning(f"Cannot place role below target {target_role.name} - target too low")
            return None
            
        return desired_pos

    async def _position_role_safely(self, role: discord.Role, target_position: int, reason: str = "Positioning custom role"):
        """Safely position a role with proper error handling and retries."""
        if role.position == target_position:
            return True
            
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                async with self._position_lock:
                    # Double-check the role still exists and we can edit it
                    fresh_role = role.guild.get_role(role.id)
                    if not fresh_role:
                        self.logger.error(f"Role {role.id} no longer exists")
                        return False
                    
                    # Check if position is still valid
                    if target_position >= role.guild.me.top_role.position:
                        self.logger.error(f"Target position {target_position} exceeds bot permissions")
                        return False
                    
                    if target_position < 1:
                        self.logger.error(f"Target position {target_position} is invalid")
                        return False
                    
                    # Attempt the position change
                    await fresh_role.edit(position=target_position, reason=reason)
                    
                    # Verify the position was set correctly
                    await asyncio.sleep(0.5)  # Give Discord time to update
                    updated_role = role.guild.get_role(role.id)
                    if updated_role and updated_role.position == target_position:
                        return True
                    else:
                        self.logger.warning(f"Role position verification failed on attempt {attempt + 1}")
                        
            except discord.Forbidden:
                self.logger.error(f"Forbidden: Cannot position role {role.name} - insufficient permissions")
                return False
            except discord.HTTPException as e:
                if attempt < max_retries - 1:
                    self.logger.warning(f"HTTP error positioning role {role.name}, retrying: {e}")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    self.logger.error(f"Failed to position role {role.name} after {max_retries} attempts: {e}")
                    return False
            except Exception as e:
                self.logger.error(f"Unexpected error positioning role {role.name}: {e}")
                return False
        
        return False

    async def _position_role_above_target(self, role: discord.Role, target_role: discord.Role):
        """Position a role above the target role (for primary roles)."""
        target_position = await self._get_safe_position_above_target(target_role, role.guild)
        if target_position is None:
            return False
        
        return await self._position_role_safely(
            role, 
            target_position, 
            "Positioning primary custom role above target"
        )

    async def _position_role_below_target(self, role: discord.Role, target_role: discord.Role):
        """Position a role below the target role (for non-primary roles)."""
        target_position = await self._get_safe_position_below_target(target_role)
        if target_position is None:
            return False
        
        return await self._position_role_safely(
            role, 
            target_position, 
            "Positioning non-primary custom role below target"
        )

async def setup(bot):
    await bot.add_cog(CustomRoles(bot))