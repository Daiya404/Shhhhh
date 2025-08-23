import discord
from discord.ext import commands
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
    "no_roles_set": "No level roles are configured for this server yet.",
    "xp_added": "Okay, I've added **{amount:,}** XP to {user}. They are now **Level {level}**.",
    "xp_removed": "Done. I've removed **{amount:,}** XP from {user}. They are now **Level {level}**."
}

class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.settings_file = Path("data/role_settings.json")
        self.levels_file = Path("data/leveling_data.json")
        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        self.user_data: Dict[str, Dict] = self._load_json(self.levels_file)
        self.cooldowns: Dict[int, Dict[int, float]] = {}

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
        return self.settings_data.get(str(guild_id), {}).get("leveling_config", {
            "min_xp": 15, "max_xp": 25, "cooldown": 60
        })

    # --- Core Logic ---
    async def process_xp(self, message: discord.Message):
        if not message.guild or message.author.bot: return
        gid, uid = message.guild.id, message.author.id
        config = self._get_level_config(gid)
        now = time.time()
        self.cooldowns.setdefault(gid, {})
        if (now - self.cooldowns[gid].get(uid, 0)) < config["cooldown"]: return
        self.cooldowns[gid][uid] = now
        await self._add_xp(message.guild, message.author, random.randint(config["min_xp"], config["max_xp"]))

    async def _add_xp(self, guild: discord.Guild, user: discord.Member, amount: int):
        gid_str, uid_str = str(guild.id), str(user.id)
        self.user_data.setdefault(gid_str, {})
        user_level_data = self.user_data[gid_str].setdefault(uid_str, {"xp": 0, "level": 0})
        
        old_level = user_level_data["level"]
        user_level_data["xp"] = max(0, user_level_data["xp"] + amount)
        new_level = self._level_for_xp(user_level_data["xp"])
        
        if new_level != old_level:
            user_level_data["level"] = new_level
            await self._update_roles_for_level(guild, user, new_level)
            if new_level > old_level:
                # Find a channel to announce the level up
                if isinstance(self.bot.get_channel(user.dm_channel.id), discord.DMChannel):
                    channel = user.dm_channel
                else:
                    channel = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
                if channel:
                    await channel.send(PERSONALITY["level_up"].format(user=user.mention, level=new_level))

        await self._save_json(self.user_data, self.levels_file)
        return user_level_data["level"]

    def _xp_for_level(self, level: int) -> int:
        return 5 * (level ** 2) + 50 * level + 100

    def _level_for_xp(self, xp: int) -> int:
        level = 0
        while True:
            xp_needed = self._xp_for_level(level + 1)
            if xp < xp_needed:
                return level
            level += 1

    async def _update_roles_for_level(self, guild: discord.Guild, user: discord.Member, new_level: int):
        level_roles_config = self.settings_data.get(str(guild.id), {}).get("level_roles", {})
        if not level_roles_config: return
        
        # Convert string keys to int for proper comparison
        level_roles = {int(k): v for k, v in level_roles_config.items()}
        
        roles_to_add = set()
        roles_to_remove = set()

        # Determine the highest role the user has earned
        highest_earned_role_id = None
        for level_tier in sorted(level_roles.keys(), reverse=True):
            if new_level >= level_tier:
                highest_earned_role_id = level_roles[level_tier]
                break

        # Add the highest earned role and remove all others
        for level_tier, role_id in level_roles.items():
            role = guild.get_role(role_id)
            if not role: continue
            
            if role_id == highest_earned_role_id:
                if role not in user.roles:
                    roles_to_add.add(role)
            else:
                if role in user.roles:
                    roles_to_remove.add(role)

        if roles_to_add:
            await user.add_roles(*roles_to_add, reason=f"Leveling system reward")
            added_role = list(roles_to_add)[0] # Assuming one role is added at a time in this logic
            if isinstance(self.bot.get_channel(user.dm_channel.id), discord.DMChannel):
                channel = user.dm_channel
            else:
                channel = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
            if channel:
                await channel.send(PERSONALITY["role_reward"].format(level=new_level, role_name=added_role.name))
        if roles_to_remove:
            await user.remove_roles(*roles_to_remove, reason="Leveling system role progression")

    # --- User Commands ---
    @app_commands.command(name="rank", description="Check your or another user's level and rank.")
    @app_commands.describe(user="The user to check the rank of.")
    async def rank(self, i: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or i.user; gid, uid = str(i.guild.id), str(target.id)
        user_data = self.user_data.get(gid, {}).get(uid)
        if not user_data: return await i.response.send_message(f"{target.display_name} hasn't earned any XP yet.", ephemeral=True)
        xp, level = user_data["xp"], user_data["level"]
        xp_needed = self._xp_for_level(level + 1); xp_of_current_level = self._xp_for_level(level)
        progress, progress_needed = xp - xp_of_current_level, xp_needed - xp_of_current_level
        embed = discord.Embed(title=f"Rank for {target.display_name}", color=target.color)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Level", value=f"`{level}`", inline=True); embed.add_field(name="Total XP", value=f"`{xp:,}`", inline=True)
        embed.add_field(name="Progress", value=f"`{progress:,} / {progress_needed:,}` XP to next level", inline=False)
        await i.response.send_message(embed=embed)
        
    @app_commands.command(name="leaderboard", description="Show the server's XP leaderboard.")
    async def leaderboard(self, i: discord.Interaction, page: app_commands.Range[int, 1, 100] = 1):
        gid = str(i.guild.id); scores = self.user_data.get(gid, {})
        if not scores: return await i.response.send_message("No one has earned any XP yet.", ephemeral=True)
        sorted_users = sorted(scores.items(), key=lambda item: item[1]['xp'], reverse=True)
        embed = discord.Embed(title="🏆 Server Leaderboard", color=0xffd700)
        start, end = (page - 1) * 10, page * 10
        lb_text = ""
        for rank, (user_id, data) in enumerate(sorted_users[start:end], start=start + 1):
            user = self.bot.get_user(int(user_id)); name = user.display_name if user else f"Unknown ({user_id})"
            lb_text += f"**{rank}.** {name} - **Level {data['level']}** ({data['xp']:,} XP)\n"
        embed.description = lb_text or "No users on this page."; embed.set_footer(text=f"Page {page}/{((len(sorted_users)-1)//10)+1}")
        await i.response.send_message(embed=embed)

    # --- Admin Commands ---
    admin_group = app_commands.Group(name="level-admin", description="Admin commands for the leveling system.")
    
    @admin_group.command(name="add-xp", description="Manually add XP to a user.")
    @app_commands.describe(user="The user to give XP to.", amount="The amount of XP to add.")
    @BotAdmin.is_bot_admin()
    async def add_xp(self, i: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]):
        new_level = await self._add_xp(i.guild, user, amount)
        await i.response.send_message(PERSONALITY["xp_added"].format(amount=amount, user=user.mention, level=new_level), ephemeral=True)

    @admin_group.command(name="remove-xp", description="Manually remove XP from a user.")
    @app_commands.describe(user="The user to take XP from.", amount="The amount of XP to remove.")
    @BotAdmin.is_bot_admin()
    async def remove_xp(self, i: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]):
        new_level = await self._add_xp(i.guild, user, -amount) # Use negative amount
        await i.response.send_message(PERSONALITY["xp_removed"].format(amount=amount, user=user.mention, level=new_level), ephemeral=True)

    @admin_group.command(name="set-xp-rate", description="Set the min/max XP gained per message.")
    @app_commands.describe(min_xp="The minimum XP to grant.", max_xp="The maximum XP to grant.")
    @BotAdmin.is_bot_admin()
    async def set_xp_rate(self, i: discord.Interaction, min_xp: app_commands.Range[int, 1, 100], max_xp: app_commands.Range[int, 1, 200]):
        if min_xp >= max_xp: return await i.response.send_message("Min XP must be less than Max XP.", ephemeral=True)
        gid = str(i.guild.id); config = self.settings_data.setdefault(gid, {}).setdefault("leveling_config", {})
        config["min_xp"] = min_xp; config["max_xp"] = max_xp
        await self._save_json(self.settings_data, self.settings_file)
        await i.response.send_message(PERSONALITY["settings_updated"], ephemeral=True)
        
    @admin_group.command(name="set-xp-cooldown", description="Set the cooldown between gaining XP.")
    @app_commands.describe(seconds="How many seconds a user must wait to get XP again.")
    @BotAdmin.is_bot_admin()
    async def set_xp_cooldown(self, i: discord.Interaction, seconds: app_commands.Range[int, 5, 300]):
        gid = str(i.guild.id); config = self.settings_data.setdefault(gid, {}).setdefault("leveling_config", {})
        config["cooldown"] = seconds
        await self._save_json(self.settings_data, self.settings_file)
        await i.response.send_message(PERSONALITY["settings_updated"], ephemeral=True)
        
    @admin_group.command(name="set-level-role", description="Assign a role reward for reaching a specific level.")
    @app_commands.describe(level="The level to reward (must be a multiple of 10).", role="The role to grant.")
    @app_commands.choices(level=[app_commands.Choice(name=str(i), value=i) for i in range(10, 101, 10)])
    @BotAdmin.is_bot_admin()
    async def set_level_role(self, i: discord.Interaction, level: int, role: discord.Role):
        gid = str(i.guild.id); level_roles = self.settings_data.setdefault(gid, {}).setdefault("level_roles", {})
        level_roles[str(level)] = role.id
        await self._save_json(self.settings_data, self.settings_file)
        await i.response.send_message(PERSONALITY["role_set"].format(level=level, role=role.mention), ephemeral=True)
        
    @admin_group.command(name="remove-level-role", description="Remove a role reward for a level.")
    @app_commands.describe(level="The level to remove the reward from.")
    @app_commands.choices(level=[app_commands.Choice(name=str(i), value=i) for i in range(10, 101, 10)])
    @BotAdmin.is_bot_admin()
    async def remove_level_role(self, i: discord.Interaction, level: int):
        gid = str(i.guild.id); level_roles = self.settings_data.setdefault(gid, {}).setdefault("level_roles", {})
        if str(level) in level_roles: del level_roles[str(level)]; await self._save_json(self.settings_data, self.settings_file)
        await i.response.send_message(PERSONALITY["role_unset"].format(level=level), ephemeral=True)
        
    @admin_group.command(name="view-roles", description="View the current level role configuration.")
    @BotAdmin.is_bot_admin()
    async def view_roles(self, i: discord.Interaction):
        gid = str(i.guild.id); level_roles = self.settings_data.get(gid, {}).get("level_roles", {})
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