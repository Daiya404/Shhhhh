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
        
        # 1. Get RAM usage from our new service
        memory_mb = self.resource_monitor.get_memory_usage_mb()
        
        # 2. Get latency (ping) from the bot
        latency_ms = self.bot.latency * 1000
        
        # 3. Calculate uptime from the bot's start_time
        if self.bot.start_time:
            uptime_delta = datetime.now(timezone.utc) - self.bot.start_time
            hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours}h {minutes}m {seconds}s"
        else:
            uptime_str = "Calculating..."

        # Determine embed color based on memory usage
        if memory_mb < 250: color = discord.Color.green()
        elif memory_mb < 500: color = discord.Color.yellow()
        else: color = discord.Color.red()

        embed = discord.Embed(
            title="Tika Performance Report",
            description="Hmph. My current vitals are listed below. Try not to give me any more unnecessary work.",
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="🧠 RAM Usage", value=f"**{memory_mb:.2f} MB**", inline=True)
        embed.add_field(name="⚡ Latency", value=f"**{latency_ms:.0f} ms**", inline=True)
        embed.add_field(name="⏳ Uptime", value=f"**{uptime_str}**", inline=True)
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    if hasattr(bot, 'resource_monitor'):
        await bot.add_cog(PerformanceMonitor(bot))
    else:
        logging.getLogger(__name__).warning("Skipping load of PerformanceMonitor cog: ResourceMonitor service not found.")