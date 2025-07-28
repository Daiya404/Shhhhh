import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import re
import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

class CustomRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.custom_roles_file = 'data/custom_roles.json'
        self.user_roles_file = 'data/user_custom_roles.json'
        self.custom_roles = self.load_custom_roles()
        self.user_custom_roles = self.load_user_custom_roles()
        
        # Role ID to place custom roles above
        self.target_role_id = 932258813770338404
        
        # Enhanced caching and rate limiting
        self._role_cache = {}
        self._guild_cache = {}
        self._cache_ttl = 300  # 5 minutes
        self._last_cache_update = {}
        self._save_lock = asyncio.Lock()
        self._position_lock = asyncio.Lock()  # Separate lock for positioning
        
        # Rate limiting for Discord API
        self._last_api_call = {}
        self._api_cooldown = 1.0  # Minimum seconds between API calls
        
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)
        
        # Set up logging
        self.logger = logging.getLogger(__name__)

    def load_custom_roles(self) -> Dict[str, Dict]:
        """Load custom roles with better error handling"""
        if not os.path.exists(self.custom_roles_file):
            return {}
        
        try:
            with open(self.custom_roles_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, FileNotFoundError, PermissionError) as e:
            self.logger.error(f"Error loading custom roles: {e}")
            return {}

    def load_user_custom_roles(self) -> Dict[str, Dict]:
        """Load user custom roles with better error handling"""
        if not os.path.exists(self.user_roles_file):
            return {}
        
        try:
            with open(self.user_roles_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, FileNotFoundError, PermissionError) as e:
            self.logger.error(f"Error loading user custom roles: {e}")
            return {}

    async def save_data_atomic(self, data: dict, filepath: str):
        """Atomic save with backup for any data file"""
        async with self._save_lock:
            try:
                # Create backup if file exists
                if os.path.exists(filepath):
                    backup_file = f"{filepath}.backup"
                    with open(filepath, 'r', encoding='utf-8') as src, \
                         open(backup_file, 'w', encoding='utf-8') as dst:
                        dst.write(src.read())
                
                # Write to temporary file first
                temp_file = f"{filepath}.tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # Atomic replace
                os.replace(temp_file, filepath)
                
            except Exception as e:
                self.logger.error(f"Error saving {filepath}: {e}")
                raise

    async def save_custom_roles(self):
        """Save custom roles"""
        await self.save_data_atomic(self.custom_roles, self.custom_roles_file)

    async def save_user_custom_roles(self):
        """Save user custom roles"""
        await self.save_data_atomic(self.user_custom_roles, self.user_roles_file)

    def validate_role_name(self, name: str) -> Tuple[bool, str]:
        """Validate role name with detailed feedback"""
        if not name or not isinstance(name, str):
            return False, "Role name cannot be empty"
        
        name = name.strip()
        if len(name) == 0:
            return False, "Role name cannot be empty"
        if len(name) > 100:
            return False, "Role name cannot exceed 100 characters"
        
        # Check for problematic characters and Discord markdown
        if re.search(r'[@#`\\*_~|]', name):
            return False, "Role name contains invalid characters"
        
        # Check for excessive whitespace
        if re.search(r'\s{3,}', name):
            return False, "Role name has too much whitespace"
        
        return True, name

    def hex_to_discord_color(self, hex_color: str) -> Optional[discord.Color]:
        """Convert hex color to Discord color with better validation"""
        if not hex_color or not isinstance(hex_color, str):
            return None
            
        hex_color = hex_color.strip().lstrip('#')
        
        # Support 3-digit hex codes
        if len(hex_color) == 3:
            hex_color = ''.join([c*2 for c in hex_color])
        
        if not re.match(r"^[0-9A-Fa-f]{6}$", hex_color):
            return None
        
        try:
            color_value = int(hex_color, 16)
            return discord.Color(color_value)
        except (ValueError, OverflowError):
            return None

    async def get_cached_guild_data(self, guild: discord.Guild) -> dict:
        """Get cached guild data including roles and bot permissions"""
        cache_key = f"guild_{guild.id}"
        current_time = datetime.now(timezone.utc).timestamp()
        
        # Check cache validity
        if (cache_key in self._guild_cache and 
            cache_key in self._last_cache_update and
            current_time - self._last_cache_update[cache_key] < self._cache_ttl):
            return self._guild_cache[cache_key]
        
        # Refresh cache
        bot_member = guild.get_member(self.bot.user.id)
        target_role = guild.get_role(self.target_role_id)
        
        cache_data = {
            'bot_member': bot_member,
            'target_role': target_role,
            'bot_top_role_position': bot_member.top_role.position if bot_member else 0,
            'target_role_position': target_role.position if target_role else 0,
            'can_manage_roles': bot_member.guild_permissions.manage_roles if bot_member else False
        }
        
        self._guild_cache[cache_key] = cache_data
        self._last_cache_update[cache_key] = current_time
        
        return cache_data

    async def rate_limit_api_call(self, key: str):
        """Simple rate limiting for API calls"""
        current_time = datetime.now(timezone.utc).timestamp()
        last_call = self._last_api_call.get(key, 0)
        
        if current_time - last_call < self._api_cooldown:
            sleep_time = self._api_cooldown - (current_time - last_call)
            await asyncio.sleep(sleep_time)
        
        self._last_api_call[key] = datetime.now(timezone.utc).timestamp()

    async def position_role_optimized(self, role: discord.Role, guild: discord.Guild) -> bool:
        """Optimized role positioning with better logic"""
        async with self._position_lock:  # Prevent concurrent positioning
            try:
                guild_data = await self.get_cached_guild_data(guild)
                
                if not guild_data['can_manage_roles']:
                    self.logger.warning(f"No permission to manage roles in guild {guild.id}")
                    return False
                
                if not guild_data['target_role']:
                    self.logger.warning(f"Target role {self.target_role_id} not found in guild {guild.id}")
                    return False
                
                # Calculate optimal position
                bot_max_position = guild_data['bot_top_role_position'] - 1
                target_position = guild_data['target_role_position']
                desired_position = min(bot_max_position, target_position + 1)
                
                # Check if already in correct position
                if abs(role.position - desired_position) <= 1:
                    return True
                
                # Rate limit the positioning call
                await self.rate_limit_api_call(f"position_role_{guild.id}")
                
                # Use modify_role_positions for more precise control
                positions = {role: desired_position}
                await guild.edit_role_positions(positions, reason="Positioning custom role")
                
                # Invalidate cache after successful positioning
                cache_key = f"guild_{guild.id}"
                if cache_key in self._guild_cache:
                    del self._guild_cache[cache_key]
                    del self._last_cache_update[cache_key]
                
                return True
                
            except discord.HTTPException as e:
                if e.status == 429:  # Rate limited
                    retry_after = getattr(e, 'retry_after', 2.0)
                    self.logger.warning(f"Rate limited positioning role, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    return False
                else:
                    self.logger.error(f"HTTP error positioning role: {e}")
                    return False
            except Exception as e:
                self.logger.error(f"Unexpected error positioning role: {e}")
                return False

    async def cleanup_orphaned_role_data(self, guild: discord.Guild):
        """Clean up data for roles that no longer exist"""
        guild_id = str(guild.id)
        if guild_id not in self.user_custom_roles:
            return 0
        
        to_remove = []
        for user_id, role_data in self.user_custom_roles[guild_id].items():
            role_id = role_data.get('role_id')
            if role_id and not guild.get_role(role_id):
                to_remove.append(user_id)
        
        for user_id in to_remove:
            del self.user_custom_roles[guild_id][user_id]
            self.logger.info(f"Cleaned up orphaned role data for user {user_id}")
        
        if not self.user_custom_roles[guild_id]:
            del self.user_custom_roles[guild_id]
        
        if to_remove:
            await self.save_user_custom_roles()
        
        return len(to_remove)

    @app_commands.command(name="customrole", description="Create or update your personal custom role")
    @app_commands.describe(
        name="Name for your custom role (max 100 characters)",
        color="Color in hex format (e.g., #ff0000 for red, or #f00 for short)"
    )
    async def create_custom_role(self, interaction: discord.Interaction, name: str, color: str = "#ffffff"):
        await interaction.response.defer(ephemeral=True)
        
        # Validate inputs
        is_valid, validated_name = self.validate_role_name(name)
        if not is_valid:
            await interaction.followup.send(f"❌ {validated_name}", ephemeral=True)
            return
        
        discord_color = self.hex_to_discord_color(color)
        if discord_color is None:
            await interaction.followup.send("❌ Invalid color format! Use hex like #ff0000 or #f00", ephemeral=True)
            return
        
        guild = interaction.guild
        user = interaction.user
        user_id = str(user.id)
        guild_id = str(guild.id)
        
        # Get cached guild data
        guild_data = await self.get_cached_guild_data(guild)
        
        if not guild_data['can_manage_roles']:
            await interaction.followup.send("❌ I don't have permission to manage roles!", ephemeral=True)
            return
        
        if guild_id not in self.user_custom_roles:
            self.user_custom_roles[guild_id] = {}
        
        try:
            # Check for existing role
            existing_role = None
            if user_id in self.user_custom_roles[guild_id]:
                existing_role_id = self.user_custom_roles[guild_id][user_id].get('role_id')
                if existing_role_id:
                    existing_role = guild.get_role(existing_role_id)
            
            if existing_role:
                # Update existing role
                await self.rate_limit_api_call(f"edit_role_{guild.id}")
                
                await existing_role.edit(
                    name=validated_name, 
                    color=discord_color,
                    reason=f"Custom role updated by {user.display_name}"
                )
                
                # Position the role
                positioning_success = await self.position_role_optimized(existing_role, guild)
                
                # Update data
                self.user_custom_roles[guild_id][user_id].update({
                    'name': validated_name,
                    'color': color.lower(),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                })
                
                await self.save_user_custom_roles()
                
                embed = discord.Embed(
                    title="✅ Custom Role Updated",
                    description=f"Your custom role **{validated_name}** has been updated!",
                    color=discord_color
                )
                
                if not positioning_success:
                    embed.add_field(
                        name="⚠️ Positioning Note", 
                        value="Role may not be in optimal position due to Discord limitations.",
                        inline=False
                    )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create new role
            await self.rate_limit_api_call(f"create_role_{guild.id}")
            
            new_role = await guild.create_role(
                name=validated_name,
                color=discord_color,
                mentionable=True,
                reason=f"Custom role created by {user.display_name}"
            )
            
            # Position the role immediately after creation
            positioning_success = await self.position_role_optimized(new_role, guild)
            
            # Assign to user with retry logic
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    await self.rate_limit_api_call(f"assign_role_{guild.id}")
                    await user.add_roles(new_role, reason="Assigning custom role")
                    break
                except discord.HTTPException as e:
                    if attempt == max_retries - 1:
                        # Clean up the role if we can't assign it
                        try:
                            await new_role.delete(reason="Failed to assign to user")
                        except:
                            pass
                        await interaction.followup.send(f"❌ Created role but failed to assign: {str(e)}", ephemeral=True)
                        return
                    await asyncio.sleep(1)
            
            # Store data
            self.user_custom_roles[guild_id][user_id] = {
                'role_id': new_role.id,
                'name': validated_name,
                'color': color.lower(),
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            
            await self.save_user_custom_roles()
            
            embed = discord.Embed(
                title="✅ Custom Role Created",
                description=f"Your custom role **{validated_name}** has been created and assigned!",
                color=discord_color
            )
            embed.add_field(name="Role ID", value=str(new_role.id), inline=True)
            embed.add_field(name="Position", value=str(new_role.position), inline=True)
            
            if not positioning_success:
                embed.add_field(
                    name="⚠️ Positioning Note", 
                    value="Role may not be in optimal position. This can happen due to Discord's role hierarchy limits.",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have sufficient permissions!", ephemeral=True)
        except discord.HTTPException as e:
            if e.status == 429:
                await interaction.followup.send("❌ Rate limited! Please wait a moment before trying again.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Discord API error: {str(e)}", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Unexpected error in create_custom_role: {e}")
            await interaction.followup.send("❌ An unexpected error occurred. Please try again later.", ephemeral=True)

    @app_commands.command(name="deletecustomrole", description="Delete your personal custom role")
    async def delete_custom_role(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
        user = interaction.user
        user_id = str(user.id)
        guild_id = str(guild.id)
        
        if (guild_id not in self.user_custom_roles or user_id not in self.user_custom_roles[guild_id]):
            await interaction.followup.send("❌ You don't have a custom role to delete!", ephemeral=True)
            return
        
        role_data = self.user_custom_roles[guild_id][user_id]
        role = guild.get_role(role_data.get('role_id'))
        
        if not role:
            # Clean up orphaned data
            del self.user_custom_roles[guild_id][user_id]
            if not self.user_custom_roles[guild_id]:
                del self.user_custom_roles[guild_id]
            await self.save_user_custom_roles()
            await interaction.followup.send("❌ Role no longer exists! Data cleaned up.", ephemeral=True)
            return
        
        try:
            role_name = role.name
            await self.rate_limit_api_call(f"delete_role_{guild.id}")
            await role.delete(reason=f"Custom role deleted by {user.display_name}")
            
            del self.user_custom_roles[guild_id][user_id]
            if not self.user_custom_roles[guild_id]:
                del self.user_custom_roles[guild_id]
            
            await self.save_user_custom_roles()
            
            embed = discord.Embed(
                title="✅ Custom Role Deleted",
                description=f"Your custom role **{role_name}** has been deleted!",
                color=0xff4444
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to delete that role!", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error deleting custom role: {e}")
            await interaction.followup.send("❌ An error occurred while deleting the role.", ephemeral=True)

    @app_commands.command(name="mycustomrole", description="View your custom role information")
    async def view_custom_role(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        user_id = str(user.id)
        guild_id = str(guild.id)
        
        if (guild_id not in self.user_custom_roles or user_id not in self.user_custom_roles[guild_id]):
            await interaction.response.send_message("❌ You don't have a custom role! Use `/customrole` to create one.", ephemeral=True)
            return
        
        role_data = self.user_custom_roles[guild_id][user_id]
        role = guild.get_role(role_data.get('role_id'))
        
        if not role:
            # Clean up orphaned data
            del self.user_custom_roles[guild_id][user_id]
            if not self.user_custom_roles[guild_id]:
                del self.user_custom_roles[guild_id]
            await self.save_user_custom_roles()
            await interaction.response.send_message("❌ Your custom role no longer exists! Use `/customrole` to create a new one.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🎭 Your Custom Role",
            description=f"**{role.name}**",
            color=role.color
        )
        embed.add_field(name="Color", value=role_data.get('color', '#ffffff').upper(), inline=True)
        embed.add_field(name="Position", value=str(role.position), inline=True)
        embed.add_field(name="Members", value=str(len(role.members)), inline=True)
        embed.add_field(name="Role ID", value=str(role.id), inline=True)
        
        if role_data.get('created_at'):
            try:
                created_dt = datetime.fromisoformat(role_data['created_at'].replace('Z', '+00:00'))
                created_timestamp = int(created_dt.timestamp())
                embed.add_field(name="Created", value=f"<t:{created_timestamp}:R>", inline=True)
            except (ValueError, AttributeError):
                pass
        
        if role_data.get('updated_at') and role_data.get('updated_at') != role_data.get('created_at'):
            try:
                updated_dt = datetime.fromisoformat(role_data['updated_at'].replace('Z', '+00:00'))
                updated_timestamp = int(updated_dt.timestamp())
                embed.add_field(name="Last Updated", value=f"<t:{updated_timestamp}:R>", inline=True)
            except (ValueError, AttributeError):
                pass
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="cleanuproles", description="Clean up orphaned custom role data (Admin only)")
    async def cleanup_roles(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command!", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            cleaned_count = await self.cleanup_orphaned_role_data(interaction.guild)
            if cleaned_count > 0:
                await interaction.followup.send(f"✅ Cleanup completed! Removed {cleaned_count} orphaned role entries.", ephemeral=True)
            else:
                await interaction.followup.send("✅ Cleanup completed! No orphaned data found.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            await interaction.followup.send("❌ An error occurred during cleanup.", ephemeral=True)

    @app_commands.command(name="roleinfo", description="Get information about role positioning (Admin only)")
    async def role_info(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command!", ephemeral=True)
            return
        
        guild_data = await self.get_cached_guild_data(interaction.guild)
        
        embed = discord.Embed(title="🔧 Role System Information", color=0x5865f2)
        embed.add_field(name="Bot Can Manage Roles", value="✅" if guild_data['can_manage_roles'] else "❌", inline=True)
        embed.add_field(name="Bot Top Role Position", value=str(guild_data['bot_top_role_position']), inline=True)
        embed.add_field(name="Target Role Found", value="✅" if guild_data['target_role'] else "❌", inline=True)
        
        if guild_data['target_role']:
            embed.add_field(name="Target Role Position", value=str(guild_data['target_role_position']), inline=True)
            embed.add_field(name="Target Role Name", value=guild_data['target_role'].name, inline=True)
        
        # Count active custom roles
        guild_id = str(interaction.guild.id)
        active_roles = len(self.user_custom_roles.get(guild_id, {}))
        embed.add_field(name="Active Custom Roles", value=str(active_roles), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(CustomRoles(bot))