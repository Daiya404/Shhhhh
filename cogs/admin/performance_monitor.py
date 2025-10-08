# cogs/admin/performance_monitor.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime, timezone

from cogs.admin.bot_admin import is_bot_admin

class PerformanceMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.resource_monitor = self.bot.resource_monitor

    @app_commands.command(name="performance", description="[Admin] Check my current performance and resource usage.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    async def performance(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # --- OPTIMIZATION: Gather a richer set of metrics ---
        memory_mb = self.resource_monitor.get_memory_usage_mb()
        cpu_percent = self.resource_monitor.get_cpu_usage_percent()
        thread_count = self.resource_monitor.get_thread_count()
        latency_ms = self.bot.latency * 1000
        guild_count = len(self.bot.guilds)
        
        # Calculate uptime using Discord's relative timestamp feature
        uptime_str = f"{discord.utils.format_dt(self.bot.start_time, style='R')}" if self.bot.start_time else "Calculating..."

        # Determine embed color based on memory usage
        if memory_mb < 250: color = discord.Color.green()
        elif memory_mb < 500: color = discord.Color.yellow()
        else: color = discord.Color.red()

        embed = discord.Embed(
            title="Tika Performance Report",
            description="Hmph. My current vitals are listed below.",
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        
        # --- OPTIMIZATION: Display more comprehensive data ---
        embed.add_field(name="🧠 RAM Usage", value=f"**{memory_mb:.2f} MB**", inline=True)
        embed.add_field(name="💻 CPU Usage", value=f"**{cpu_percent:.1f}%**", inline=True)
        embed.add_field(name="🧵 Threads", value=f"**{thread_count}**", inline=True)
        embed.add_field(name="⚡ Gateway Latency", value=f"**{latency_ms:.0f} ms**", inline=True)
        embed.add_field(name="🏠 Guilds", value=f"**{guild_count}**", inline=True)
        embed.add_field(name="⏳ Uptime", value=uptime_str, inline=True)
        
        embed.set_footer(text=f"Shard ID: {interaction.guild.shard_id if interaction.guild else 'N/A'}")
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    if hasattr(bot, 'resource_monitor') and bot.resource_monitor:
        await bot.add_cog(PerformanceMonitor(bot))
    else:
        logging.getLogger(__name__).warning("Skipping load of PerformanceMonitor cog: ResourceMonitor service not found.")