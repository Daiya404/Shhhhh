# cogs/admin/bot_admin.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional, Dict, Set
import asyncio

from config.personalities import PERSONALITY_RESPONSES

# Global cache to avoid dependency on cog instance
_admin_cache: Dict[str, Set[int]] = {}
_cache_lock = asyncio.Lock()

def is_bot_admin():
    """
    Ultra-fast decorator that checks bot admin permissions.
    Uses a global in-memory cache with instant lookups.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        # Rule 1: Server administrators are always bot admins (fastest check)
        if interaction.user.guild_permissions.administrator:
            return True
        
        # Rule 2: Fast cache lookup (no async operations)
        guild_id_str = str(interaction.guild_id)
        guild_admins = _admin_cache.get(guild_id_str, set())
        
        return interaction.user.id in guild_admins
    
    return app_commands.check(predicate)


class BotAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["bot_admin"]
        self.data_manager = self.bot.data_manager
        
        # Initialize cache immediately on cog load
        self._cache_ready = asyncio.Event()

    async def cog_load(self):
        """Load admin data once when cog starts."""
        await self._load_admin_cache()
        self._cache_ready.set()
        self.logger.info("Bot admin cache loaded and ready.")

    async def _load_admin_cache(self):
        """Load admin data into the global cache."""
        global _admin_cache
        
        try:
            async with _cache_lock:
                # Load data once
                bot_admins_data = await self.data_manager.get_data("bot_admins")
                
                # Convert to sets for O(1) lookups
                _admin_cache = {
                    guild_id: set(user_ids) 
                    for guild_id, user_ids in bot_admins_data.items()
                }
                
                self.logger.info(f"Loaded {len(_admin_cache)} guild admin configurations")
                
        except Exception as e:
            self.logger.error(f"Failed to load bot admin cache: {e}")
            _admin_cache = {}

    async def _update_cache_for_guild(self, guild_id: str, user_ids: list):
        """Update cache for a specific guild immediately."""
        global _admin_cache
        
        async with _cache_lock:
            if user_ids:
                _admin_cache[guild_id] = set(user_ids)
            else:
                # Remove empty guild entries
                _admin_cache.pop(guild_id, None)

    async def check_prefix_command(self, ctx: commands.Context) -> bool:
        """Fast check for prefix commands."""
        if ctx.author.guild_permissions.administrator:
            return True
        
        # Wait for cache to be ready if needed
        await self._cache_ready.wait()
        
        guild_admins = _admin_cache.get(str(ctx.guild.id), set())
        return ctx.author.id in guild_admins

    @app_commands.command(name="botadmin", description="Manage who can use Tika's admin commands.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        action="Add, remove, or list admins.", 
        user="The user to manage (not required for list)."
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
        app_commands.Choice(name="List", value="list"),
    ])
    async def manage_admins(self, interaction: discord.Interaction, action: str, user: Optional[discord.Member] = None):
        # Only defer for operations that might take time (data saving)
        if action in ["add", "remove"]:
            await interaction.response.defer(ephemeral=True)
        
        if action in ["add", "remove"] and not user:
            response = "You must specify a user for that action."
            if action in ["add", "remove"]:
                await interaction.followup.send(response, ephemeral=True)
            else:
                await interaction.response.send_message(response, ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        
        # Get current data from cache first
        current_admins = _admin_cache.get(guild_id, set()).copy()

        if action == "add":
            if user.id in current_admins:
                await interaction.followup.send(self.personality["already_admin"], ephemeral=True)
                return
            
            # Update cache immediately
            new_admins = current_admins | {user.id}
            await self._update_cache_for_guild(guild_id, list(new_admins))
            
            # Save to persistent storage (can be slow)
            try:
                bot_admins_data = await self.data_manager.get_data("bot_admins")
                bot_admins_data[guild_id] = list(new_admins)
                await self.data_manager.save_data("bot_admins", bot_admins_data)
                
                await interaction.followup.send(
                    self.personality["admin_added"].format(user=user.display_name)
                )
            except Exception as e:
                # Rollback cache on save failure
                await self._update_cache_for_guild(guild_id, list(current_admins))
                self.logger.error(f"Failed to save admin data: {e}")
                await interaction.followup.send("Failed to save changes. Please try again.", ephemeral=True)
        
        elif action == "remove":
            if user.id not in current_admins:
                await interaction.followup.send(self.personality["not_admin"], ephemeral=True)
                return
            
            # Update cache immediately
            new_admins = current_admins - {user.id}
            await self._update_cache_for_guild(guild_id, list(new_admins))
            
            # Save to persistent storage
            try:
                bot_admins_data = await self.data_manager.get_data("bot_admins")
                if new_admins:
                    bot_admins_data[guild_id] = list(new_admins)
                else:
                    bot_admins_data.pop(guild_id, None)
                    
                await self.data_manager.save_data("bot_admins", bot_admins_data)
                
                await interaction.followup.send(
                    self.personality["admin_removed"].format(user=user.display_name)
                )
            except Exception as e:
                # Rollback cache on save failure
                await self._update_cache_for_guild(guild_id, list(current_admins))
                self.logger.error(f"Failed to save admin data: {e}")
                await interaction.followup.send("Failed to save changes. Please try again.", ephemeral=True)

        elif action == "list":
            if not current_admins:
                await interaction.response.send_message(self.personality["no_admins"], ephemeral=True)
                return
            
            embed = discord.Embed(
                title="Delegated Bot Admins", 
                color=discord.Color.blue(), 
                description="\n".join([f"<@{uid}>" for uid in current_admins])
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(BotAdmin(bot))