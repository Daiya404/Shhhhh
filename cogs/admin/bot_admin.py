# cogs/admin/bot_admin.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
from typing import Optional

from config.personalities import PERSONALITY_RESPONSES

# --- THE NEW, FAST DECORATOR ---
def is_bot_admin():
    """
    A fast, cached custom decorator that checks if a user is a bot admin.
    It relies on a background task in the BotAdmin cog to maintain a cache,
    ensuring the check itself is instantaneous and avoids timeouts.
    """
    
    async def predicate(interaction: discord.Interaction) -> bool:
        """The actual check logic, now using a cache."""
        # Rule 1: Server Admins are always bot admins. This check is synchronous and fast.
        if interaction.user.guild_permissions.administrator:
            return True
        
        # Get the cog to access the cache.
        cog = interaction.client.get_cog('BotAdmin')
        if not cog:
            # This should ideally never happen if the cog is loaded.
            # We no longer send a message here to prevent other errors.
            # The check will just fail safely.
            logging.warning("BotAdmin cog not found for permission check.")
            return False
            
        # Rule 2: Perform a FAST, SYNCHRONOUS check against the cache.
        # NO `await` here means NO timeout!
        guild_admins = cog.admin_cache.get(str(interaction.guild_id), [])
        
        return interaction.user.id in guild_admins
    
    return app_commands.check(predicate)


class BotAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["bot_admin"]
        self.data_manager = self.bot.data_manager

        # --- NEW: Initialize the admin cache ---
        self.admin_cache = {}
        # --- NEW: Start the background task to update the cache ---
        self.update_admin_cache_task.start()

    def cog_unload(self):
        """Clean up the task when the cog is unloaded."""
        self.update_admin_cache_task.cancel()

    # --- NEW: Background task to keep the admin cache fresh ---
    @tasks.loop(seconds=60)
    async def update_admin_cache_task(self):
        """Periodically loads bot admin data into a fast in-memory cache."""
        try:
            # The slow I/O operation happens here, safely in the background.
            self.admin_cache = await self.data_manager.get_data("bot_admins")
        except Exception as e:
            self.logger.error(f"Failed to update bot admin cache: {e}")

    @update_admin_cache_task.before_loop
    async def before_update_cache(self):
        """Ensures the bot is ready before the task starts."""
        await self.bot.wait_until_ready()
        self.logger.info("Starting background task for bot admin cache.")

    # --- PREFIX COMMAND CHECK (Can also be optimized to use the cache) ---
    async def check_prefix_command(self, ctx: commands.Context) -> bool:
        """The core logic for checking if a user is a bot admin for prefix commands."""
        if ctx.author.guild_permissions.administrator:
            return True
        
        # Use the fast cache for prefix commands too
        guild_admins = self.admin_cache.get(str(ctx.guild.id), [])
        return ctx.author.id in guild_admins

    @app_commands.command(name="botadmin", description="Manage who can use Tika's admin commands.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin() # This command now uses its own fast decorator
    @app_commands.describe(action="Add, remove, or list admins.", user="The user to manage (not required for list).")
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
        app_commands.Choice(name="List", value="list"),
    ])
    async def manage_admins(self, interaction: discord.Interaction, action: str, user: Optional[discord.Member] = None):
        # We can defer here just in case the data saving is slow, but it's not strictly necessary to fix the timeout.
        await interaction.response.defer(ephemeral=True)

        if action in ["add", "remove"] and not user:
            await interaction.followup.send("You must specify a user for that action.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        # We still need to fetch the real data to modify it
        bot_admins_data = await self.data_manager.get_data("bot_admins")
        guild_admins = bot_admins_data.setdefault(guild_id, [])

        if action == "add":
            if user.id in guild_admins:
                await interaction.followup.send(self.personality["already_admin"], ephemeral=True)
                return
            guild_admins.append(user.id)
            await self.data_manager.save_data("bot_admins", bot_admins_data)
            # --- NEW: Immediately update the cache after making a change ---
            self.admin_cache = bot_admins_data
            await interaction.followup.send(self.personality["admin_added"].format(user=user.display_name))
        
        elif action == "remove":
            if user.id not in guild_admins:
                await interaction.followup.send(self.personality["not_admin"], ephemeral=True)
                return
            guild_admins.remove(user.id)
            if not guild_admins: del bot_admins_data[guild_id]
            await self.data_manager.save_data("bot_admins", bot_admins_data)
            # --- NEW: Immediately update the cache after making a change ---
            self.admin_cache = bot_admins_data
            await interaction.followup.send(self.personality["admin_removed"].format(user=user.display_name))

        elif action == "list":
            # Use the live data for the list command to ensure it's up-to-date
            if not guild_admins:
                await interaction.followup.send(self.personality["no_admins"], ephemeral=True)
                return
            embed = discord.Embed(title="Delegated Bot Admins", color=discord.Color.blue(), description="\n".join([f"<@{uid}>" for uid in guild_admins]))
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(BotAdmin(bot))