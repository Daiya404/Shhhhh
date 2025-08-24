import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
from typing import Dict, Optional
from datetime import datetime

from .bot_admin import BotAdmin

class ServerStats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # We need to read the leveling data to find active members
        self.levels_file = Path("data/leveling_data.json")

    def _load_json(self, file_path: Path) -> Dict:
        """A safe method to load JSON data."""
        if not file_path.exists(): 
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f: 
                return json.load(f)
        except (json.JSONDecodeError, IOError): 
            self.logger.error(f"Error loading {file_path}", exc_info=True)
            return {}

    @app_commands.command(name="server-stats", description="Display detailed statistics about the server.")
    @BotAdmin.is_bot_admin()
    async def server_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
        
        # --- Create the main embed ---
        embed = discord.Embed(
            title=f"📊 Server Stats for {guild.name}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
            
        # --- 1. General Information ---
        owner = guild.owner.mention if guild.owner else "Unknown"
        created_at = f"<t:{int(guild.created_at.timestamp())}:F>"
        
        embed.add_field(
            name="📋 General Info",
            value=(
                f"**Owner:** {owner}\n"
                f"**Created:** {created_at}\n"
                f"**Verification:** {str(guild.verification_level).capitalize()}"
            ),
            inline=False
        )
        
        # --- 2. Member Counts ---
        total_members = guild.member_count
        humans = sum(1 for member in guild.members if not member.bot)
        bots = total_members - humans
        online_members = sum(1 for member in guild.members if member.status != discord.Status.offline)
        
        embed.add_field(
            name="👥 Member Counts",
            value=(
                f"**Total:** {total_members}\n"
                f"**Humans:** {humans}\n"
                f"**Bots:** {bots}\n"
                f"**Online:** {online_members} ({round((online_members/total_members)*100)}%)"
            ),
            inline=True
        )
        
        # --- 3. Asset Counts ---
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        roles = len(guild.roles)
        emojis = len(guild.emojis)
        
        embed.add_field(
            name="📦 Asset Counts",
            value=(
                f"**Text Channels:** {text_channels}\n"
                f"**Voice Channels:** {voice_channels}\n"
                f"**Roles:** {roles}\n"
                f"**Emojis:** {emojis}"
            ),
            inline=True
        )
        
        # --- 4. Activity Insights (from leveling data) ---
        user_data = self._load_json(self.levels_file)
        guild_scores = user_data.get(str(guild.id), {})
        
        if guild_scores:
            # Sort users by XP to find the most active
            sorted_users = sorted(guild_scores.items(), key=lambda item: item[1]['xp'], reverse=True)
            
            top_5_text = ""
            for i, (user_id, data) in enumerate(sorted_users[:5]):
                member = guild.get_member(int(user_id))
                name = member.mention if member else f"*(User Left)*"
                top_5_text += f"`{i+1}.` {name} - **Lvl {data['level']}** ({data['xp']:,} XP)\n"
            
            if top_5_text:
                embed.add_field(
                    name="🏆 Top 5 Most Active Members",
                    value=top_5_text,
                    inline=False
                )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerStats(bot))