import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
from pathlib import Path
import logging
import random
import time
from typing import Dict, Optional

from .bot_admin import BotAdmin

# --- Personality Responses ---
PERSONALITY = {
    "level_up": "Hmph. It looks like {user} has been active. You've reached **Level {level}**.",
    "role_reward": "As a reward for reaching Level {level}, I've given you the **{role_name}** role. Don't get a big head about it.",
    "settings_updated": "Fine, I've updated the leveling settings. I hope you know what you're doing.",
    "role_set": "Okay, the role for **Level {level}** is now {role}.",
    "role_unset": "I've removed the role reward for **Level {level}**.",
    "no_roles_set": "No level roles are configured for this server yet."
}

class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        
        self.settings_file = Path("data/role_settings.json") # Shared settings file
        self.levels_file = Path("data/leveling_data.json")
        
        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        # Data: {guild_id: {user_id: {"xp": int, "level": int}}}
        self.user_data: Dict[str, Dict] = self._load_json(self.levels_file)
        
        # Cooldown management: {guild_id: {user_id: timestamp}}
        self.cooldowns: Dict[int, Dict[int, float]] = {}

    # --- Data Handling ---
    def _load_json(self, file_path: Path) -> Dict:
        if not file_path.exists(): return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError): return {}
    async def _save_json(self, data: dict, file_path: Path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except IOError: self.logger.error(f"Error saving {file_path}", exc_info=True)

    def _get_level_config(self, guild_id: int) -> Dict:
        """Gets a guild's level config with safe defaults."""
        return self.settings_data.get(str(guild_id), {}).get("leveling_config", {
            "min_xp": 15, "max_xp": 25, "cooldown": 60
        })

    # --- Core Logic for Traffic Cop ---
    async def process_xp(self, message: discord.Message):
        """This is the main function called by the Traffic Cop on every message."""
        if not message.guild or message.author.bot: return

        gid, uid = message.guild.id, message.author.id
        config = self._get_level_config(gid)
        
        # Handle Cooldown
        now = time.time()
        self.cooldowns.setdefault(gid, {})
        if (now - self.cooldowns[gid].get(uid, 0)) < config["cooldown"]:
            return
        self.cooldowns[gid][uid] = now

        # Get user data
        gid_str, uid_str = str(gid), str(uid)
        self.user_data.setdefault(gid_str, {})
        user = self.user_data[gid_str].setdefault(uid_str, {"xp": 0, "level": 0})
        
        # Add XP
        xp_to_add = random.randint(config["min_xp"], config["max_xp"])
        user["xp"] += xp_to_add
        
        # Check for level up
        xp_for_next_level = self._xp_for_level(user["level"] + 1)
        if user["xp"] >= xp_for_next_level:
            user["level"] += 1
            await self._handle_level_up(message.channel, message.author, user["level"])

        await self._save_json(self.user_data, self.levels_file)

    def _xp_for_level(self, level: int) -> int:
        """Calculates the total XP needed to reach a certain level."""
        return 5 * (level ** 2) + 50 * level + 100

    async def _handle_level_up(self, channel: discord.TextChannel, user: discord.Member, new_level: int):
        """Announces a level up and handles role rewards."""
        await channel.send(PERSONALITY["level_up"].format(user=user.mention, level=new_level))
        
        level_roles = self.settings_data.get(str(channel.guild.id), {}).get("level_roles", {})
        
        # Check if the new level is a reward tier (10, 20, 30, etc.)
        if new_level % 10 == 0 and new_level <= 100:
            role_id = level_roles.get(str(new_level))
            if not role_id: return

            new_role = channel.guild.get_role(role_id)
            if not new_role: return

            # Remove previous tier's role if it exists
            previous_tier = new_level - 10
            if previous_tier > 0:
                prev_role_id = level_roles.get(str(previous_tier))
                if prev_role_id and (prev_role := channel.guild.get_role(prev_role_id)):
                    if prev_role in user.roles:
                        await user.remove_roles(prev_role, reason="Level up role progression")

            # Add new role
            if new_role not in user.roles:
                await user.add_roles(new_role, reason=f"Reached Level {new_level}")
                await channel.send(PERSONALITY["role_reward"].format(level=new_level, role_name=new_role.name))

    # --- User Commands ---
    @app_commands.command(name="rank", description="Check your or another user's level and rank.")
    @app_commands.describe(user="The user to check the rank of.")
    async def rank(self, i: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or i.user
        gid, uid = str(i.guild.id), str(target.id)
        
        user_data = self.user_data.get(gid, {}).get(uid)
        if not user_data:
            return await i.response.send_message(f"{target.display_name} hasn't earned any XP yet.", ephemeral=True)

        xp, level = user_data["xp"], user_data["level"]
        xp_needed = self._xp_for_level(level + 1)
        xp_of_current_level = self._xp_for_level(level)
        progress = xp - xp_of_current_level
        progress_needed = xp_needed - xp_of_current_level
        
        embed = discord.Embed(title=f"Rank for {target.display_name}", color=target.color)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Level", value=f"`{level}`", inline=True)
        embed.add_field(name="Total XP", value=f"`{xp:,}`", inline=True)
        embed.add_field(name="Progress", value=f"`{progress:,} / {progress_needed:,}` XP to next level", inline=False)
        
        await i.response.send_message(embed=embed)
        
    @app_commands.command(name="leaderboard", description="Show the server's XP leaderboard.")
    async def leaderboard(self, i: discord.Interaction, page: app_commands.Range[int, 1, 100] = 1):
        gid = str(i.guild.id); scores = self.user_data.get(gid, {})
        if not scores: return await i.response.send_message("No one has earned any XP yet.", ephemeral=True)
        
        # Sort by XP, not just the dict order
        sorted_users = sorted(scores.items(), key=lambda item: item[1]['xp'], reverse=True)
        
        embed = discord.Embed(title="🏆 Server Leaderboard", color=0xffd700)
        start, end = (page - 1) * 10, page * 10
        lb_text = ""
        for rank, (user_id, data) in enumerate(sorted_users[start:end], start=start + 1):
            user = self.bot.get_user(int(user_id)); name = user.display_name if user else f"Unknown ({user_id})"
            lb_text += f"**{rank}.** {name} - **Level {data['level']}** ({data['xp']:,} XP)\n"
        embed.description = lb_text or "No users on this page."
        embed.set_footer(text=f"Page {page}/{((len(sorted_users)-1)//10)+1}")
        await i.response.send_message(embed=embed)

    # --- Admin Commands ---
    admin_group = app_commands.Group(name="level-admin", description="Admin commands for the leveling system.")
    
    @admin_group.command(name="set-xp-rate", description="Set the min/max XP gained per message.")
    @app_commands.describe(min_xp="The minimum XP to grant.", max_xp="The maximum XP to grant.")
    @BotAdmin.is_bot_admin()
    async def set_xp_rate(self, i: discord.Interaction, min_xp: app_commands.Range[int, 1, 100], max_xp: app_commands.Range[int, 1, 200]):
        if min_xp >= max_xp:
            return await i.response.send_message("Min XP must be less than Max XP.", ephemeral=True)
        
        gid = str(i.guild.id)
        config = self.settings_data.setdefault(gid, {}).setdefault("leveling_config", {})
        config["min_xp"] = min_xp
        config["max_xp"] = max_xp
        await self._save_json(self.settings_data, self.settings_file)
        await i.response.send_message(PERSONALITY["settings_updated"], ephemeral=True)
        
    @admin_group.command(name="set-xp-cooldown", description="Set the cooldown between gaining XP.")
    @app_commands.describe(seconds="How many seconds a user must wait to get XP again.")
    @BotAdmin.is_bot_admin()
    async def set_xp_cooldown(self, i: discord.Interaction, seconds: app_commands.Range[int, 5, 300]):
        gid = str(i.guild.id)
        config = self.settings_data.setdefault(gid, {}).setdefault("leveling_config", {})
        config["cooldown"] = seconds
        await self._save_json(self.settings_data, self.settings_file)
        await i.response.send_message(PERSONALITY["settings_updated"], ephemeral=True)
        
    @admin_group.command(name="set-level-role", description="Assign a role reward for reaching a specific level.")
    @app_commands.describe(level="The level to reward (must be a multiple of 10).", role="The role to grant.")
    @app_commands.choices(level=[app_commands.Choice(name=str(i), value=i) for i in range(10, 101, 10)])
    @BotAdmin.is_bot_admin()
    async def set_level_role(self, i: discord.Interaction, level: int, role: discord.Role):
        gid = str(i.guild.id)
        level_roles = self.settings_data.setdefault(gid, {}).setdefault("level_roles", {})
        level_roles[str(level)] = role.id
        await self._save_json(self.settings_data, self.settings_file)
        await i.response.send_message(PERSONALITY["role_set"].format(level=level, role=role.mention), ephemeral=True)
        
    @admin_group.command(name="remove-level-role", description="Remove a role reward for a level.")
    @app_commands.describe(level="The level to remove the reward from.")
    @app_commands.choices(level=[app_commands.Choice(name=str(i), value=i) for i in range(10, 101, 10)])
    @BotAdmin.is_bot_admin()
    async def remove_level_role(self, i: discord.Interaction, level: int):
        gid = str(i.guild.id)
        level_roles = self.settings_data.setdefault(gid, {}).setdefault("level_roles", {})
        if str(level) in level_roles:
            del level_roles[str(level)]
            await self._save_json(self.settings_data, self.settings_file)
        await i.response.send_message(PERSONALITY["role_unset"].format(level=level), ephemeral=True)
        
    @admin_group.command(name="view-roles", description="View the current level role configuration.")
    @BotAdmin.is_bot_admin()
    async def view_roles(self, i: discord.Interaction):
        gid = str(i.guild.id)
        level_roles = self.settings_data.get(gid, {}).get("level_roles", {})
        if not level_roles: return await i.response.send_message(PERSONALITY["no_roles_set"], ephemeral=True)
        
        embed = discord.Embed(title="Level Role Rewards", color=discord.Color.blue())
        desc = ""
        for level, role_id in sorted(level_roles.items(), key=lambda item: int(item[0])):
            role = i.guild.get_role(role_id)
            desc += f"**Level {level}:** {role.mention if role else '`Role Not Found`'}\n"
        embed.description = desc
        await i.response.send_message(embed=embed, ephemeral=True)
        
async def setup(bot):
    await bot.add_cog(Leveling(bot))