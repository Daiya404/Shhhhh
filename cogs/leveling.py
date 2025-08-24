import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
import random
import time
from typing import Dict, Optional
import asyncio
import io
import re

# Import the Pillow library for image manipulation
from PIL import Image, ImageDraw, ImageFont, ImageOps
import aiohttp

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
    "xp_removed": "Done. I've removed **{amount:,}** XP from {user}. They are now **Level {level}**.",
    "bg_set": "Fine, I've updated your rank card background. I hope it's not ugly.",
    "bg_invalid": "That doesn't look like a valid image URL. I couldn't download it.",
    "color_set": "Your rank card accent color has been updated to `{color}`.",
    "color_invalid": "That's not a valid hex color. Use something like `#A020F0`.",
    "card_reset": "Okay, I've reset the rank card customizations for {user}."
}

class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.session = aiohttp.ClientSession()
        
        self.settings_file = Path("data/role_settings.json")
        self.levels_file = Path("data/leveling_data.json")
        self.card_settings_file = Path("data/rank_card_settings.json")
        
        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        self.user_data: Dict[str, Dict] = self._load_json(self.levels_file)
        self.card_settings: Dict[str, Dict] = self._load_json(self.card_settings_file)
        self.cooldowns: Dict[int, Dict[int, float]] = {}

    async def cog_unload(self):
        await self.session.close()

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

    # --- Core XP Logic ---
    async def process_xp(self, message: discord.Message):
        if not message.guild or message.author.bot: return
        gid, uid = message.guild.id, message.author.id
        config = self._get_level_config(gid); now = time.time()
        self.cooldowns.setdefault(gid, {})
        if (now - self.cooldowns[gid].get(uid, 0)) < config["cooldown"]: return
        self.cooldowns[gid][uid] = now
        await self._add_xp(message.guild, message.author, random.randint(config["min_xp"], config["max_xp"]), message.channel)

    async def _add_xp(self, guild: discord.Guild, user: discord.Member, amount: int, channel: Optional[discord.TextChannel] = None):
        gid_str, uid_str = str(guild.id), str(user.id)
        self.user_data.setdefault(gid_str, {})
        user_level_data = self.user_data[gid_str].setdefault(uid_str, {"xp": 0, "level": 0})
        old_level = user_level_data["level"]; user_level_data["xp"] = max(0, user_level_data["xp"] + amount)
        new_level = self._level_for_xp(user_level_data["xp"])
        if new_level != old_level:
            user_level_data["level"] = new_level
            if channel:
                await self._update_roles_for_level(guild, user, new_level, channel)
                if new_level > old_level:
                    await channel.send(PERSONALITY["level_up"].format(user=user.mention, level=new_level))
        await self._save_json(self.user_data, self.levels_file)
        return user_level_data["level"]

    def _xp_for_level(self, level: int) -> int:
        return 5 * (level ** 2) + 50 * level + 100
    def _level_for_xp(self, xp: int) -> int:
        level = 0
        while xp >= self._xp_for_level(level + 1): level += 1
        return level

    async def _update_roles_for_level(self, guild: discord.Guild, user: discord.Member, new_level: int, channel: discord.TextChannel):
        level_roles_config = self.settings_data.get(str(guild.id), {}).get("level_roles", {})
        if not level_roles_config: return
        level_roles = {int(k): v for k, v in level_roles_config.items()}
        highest_earned_role_id = None
        for level_tier in sorted(level_roles.keys(), reverse=True):
            if new_level >= level_tier: highest_earned_role_id = level_roles[level_tier]; break
        roles_to_add, roles_to_remove = set(), set()
        for level_tier, role_id in level_roles.items():
            role = guild.get_role(role_id)
            if not role: continue
            if role_id == highest_earned_role_id:
                if role not in user.roles: roles_to_add.add(role)
            elif role in user.roles: roles_to_remove.add(role)
        if roles_to_add:
            await user.add_roles(*roles_to_add, reason="Leveling system reward")
            if channel: await channel.send(PERSONALITY["role_reward"].format(level=new_level, role_name=list(roles_to_add)[0].name))
        if roles_to_remove: await user.remove_roles(*roles_to_remove, reason="Leveling system role progression")

    # --- Image Generation ---
    async def _generate_rank_card(self, user: discord.Member, rank: int, level: int, total_xp: int, current_xp: int, needed_xp: int) -> io.BytesIO:
        gid_str, uid_str = str(user.guild.id), str(user.id)
        user_settings = self.card_settings.get(gid_str, {}).get(uid_str, {})
        bg_url = user_settings.get("background_url")
        color = user_settings.get("color", "#FFFFFF")
        avatar_data, bg_data = await self._fetch_card_images(user, bg_url)
        return await asyncio.to_thread(self._draw_card, user, rank, level, total_xp, current_xp, needed_xp, avatar_data, bg_data, color)

    async def _fetch_card_images(self, user: discord.Member, bg_url: Optional[str]):
        async def fetch(url):
            try:
                async with self.session.get(url) as resp:
                    if resp.status == 200: return await resp.read()
            except aiohttp.ClientError: return None
        tasks = [fetch(str(user.display_avatar.with_size(256)))]
        if bg_url: tasks.append(fetch(bg_url))
        results = await asyncio.gather(*tasks)
        return results[0], results[1] if bg_url else None

    def _draw_card(self, user, rank, level, total_xp, current_xp, needed_xp, avatar_data, bg_data, color_hex) -> io.BytesIO:
        W, H = 934, 282
        card = Image.new("RGBA", (W, H), (0,0,0,0))
        if bg_data:
            bg = Image.open(io.BytesIO(bg_data)).convert("RGBA")
            bg_w, bg_h = bg.size; ratio = max(W/bg_w, H/bg_h)
            bg = bg.resize((int(bg_w*ratio), int(bg_h*ratio)), Image.Resampling.LANCZOS)
            bg = bg.crop(((bg.width - W)/2, (bg.height - H)/2, (bg.width + W)/2, (bg.height + H)/2))
            card.paste(bg, (0, 0))
        overlay = Image.new("RGBA", (W, H), (40, 43, 48, 200)); card = Image.alpha_composite(card, overlay)
        draw = ImageDraw.Draw(card)
        font_big = ImageFont.truetype("assets/fonts/unisans.otf", 50)
        font_med = ImageFont.truetype("assets/fonts/unisans.otf", 35)
        font_small = ImageFont.truetype("assets/fonts/unisans.otf", 25)
        if avatar_data:
            pfp = Image.open(io.BytesIO(avatar_data)).convert("RGBA").resize((190, 190), Image.Resampling.LANCZOS)
            mask = Image.new("L", pfp.size, 0); mask_draw = ImageDraw.Draw(mask); mask_draw.ellipse((0, 0, pfp.width, pfp.height), fill=255)
            card.paste(pfp, (50, 46), mask)
        bar_x, bar_y, bar_w, bar_h, r = 280, 180, 600, 40, 20
        progress = (current_xp / needed_xp) * bar_w if needed_xp > 0 else 0
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=r, fill="#484B4E")
        if progress > 0: draw.rounded_rectangle((bar_x, bar_y, bar_x + progress, bar_y + bar_h), radius=r, fill=color_hex)
        draw.text((280, 125), user.name, font=font_big, fill="#FFFFFF")
        name_width = draw.textlength(user.name, font=font_big)
        draw.text((280 + name_width + 10, 140), f"#{user.discriminator}", font=font_small, fill="#B9BBBE")
        xp_text = f"{current_xp:,} / {needed_xp:,} XP"
        xp_width = draw.textlength(xp_text, font_small)
        draw.text((W - 50 - xp_width, 140), xp_text, font_small, fill="#B9BBBE")
        rank_text = f"#{rank}"; rank_width = draw.textlength(rank_text, font=font_big)
        draw.text((W - 50 - rank_width, 50), rank_text, font=font_big, fill="#FFFFFF")
        rank_label_width = draw.textlength("RANK", font=font_med)
        draw.text((W - 50 - rank_width - 20 - rank_label_width, 60), "RANK", font=font_med, fill="#B9BBBE")
        level_text = str(level); level_width = draw.textlength(level_text, font=font_big)
        level_label_width = draw.textlength("LEVEL", font=font_med)
        level_start_x = W - 50 - rank_width - 20 - rank_label_width - 50 - level_width
        draw.text((level_start_x, 50), level_text, font=font_big, fill="#FFFFFF")
        draw.text((level_start_x - 20 - level_label_width, 60), "LEVEL", font=font_med, fill="#B9BBBE")
        buffer = io.BytesIO(); card.save(buffer, format="PNG"); buffer.seek(0)
        return buffer

    # --- User Commands ---
    @app_commands.command(name="rank", description="Check your or another user's level and rank.")
    @app_commands.describe(user="The user to check the rank of.")
    async def rank(self, i: discord.Interaction, user: Optional[discord.Member] = None):
        await i.response.defer()
        target = user or i.user; gid, uid = str(i.guild.id), str(target.id)
        scores = self.user_data.get(gid, {})
        if not scores or uid not in scores: return await i.followup.send(f"{target.display_name} hasn't earned any XP yet.")
        sorted_users = sorted(scores.items(), key=lambda item: item[1]['xp'], reverse=True)
        rank = next((r + 1 for r, (user_id, _) in enumerate(sorted_users) if user_id == uid), 0)
        user_data = scores[uid]; xp, level = user_data["xp"], user_data["level"]
        xp_for_current, xp_for_next = self._xp_for_level(level), self._xp_for_level(level + 1)
        current_progress, needed_progress = xp - xp_for_current, xp_for_next - xp_for_current
        card_buffer = await self._generate_rank_card(target, rank, level, xp, current_progress, needed_progress)
        file = discord.File(fp=card_buffer, filename="rank_card.png")
        await i.followup.send(file=file)
        
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

    # --- Card Customization Commands ---
    card_group = app_commands.Group(name="rank-card", description="Customize your personal rank card.")
    
    @card_group.command(name="set-background", description="Set a custom background image for your rank card.")
    @app_commands.describe(image_url="A direct link to an image (jpg, png, gif).")
    async def set_background(self, i: discord.Interaction, image_url: str):
        try:
            async with self.session.head(image_url) as resp:
                if resp.status != 200 or not resp.content_type.startswith("image/"):
                    return await i.response.send_message(PERSONALITY["bg_invalid"], ephemeral=True)
        except aiohttp.ClientError: return await i.response.send_message(PERSONALITY["bg_invalid"], ephemeral=True)
        gid_str, uid_str = str(i.guild.id), str(i.user.id)
        self.card_settings.setdefault(gid_str, {}).setdefault(uid_str, {})["background_url"] = image_url
        await self._save_json(self.card_settings, self.card_settings_file)
        await i.response.send_message(PERSONALITY["bg_set"], ephemeral=True)

    @card_group.command(name="set-color", description="Set a custom accent color for your rank card.")
    @app_commands.describe(hex_code="The color in hex format (e.g., #A020F0).")
    async def set_color(self, i: discord.Interaction, hex_code: str):
        if not re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", hex_code):
            return await i.response.send_message(PERSONALITY["color_invalid"], ephemeral=True)
        gid_str, uid_str = str(i.guild.id), str(i.user.id)
        self.card_settings.setdefault(gid_str, {}).setdefault(uid_str, {})["color"] = hex_code
        await self._save_json(self.card_settings, self.card_settings_file)
        await i.response.send_message(PERSONALITY["color_set"].format(color=hex_code.upper()), ephemeral=True)

    @card_group.command(name="reset", description="[Admin] Reset a user's rank card customizations.")
    @app_commands.describe(user="The user whose card to reset.")
    @BotAdmin.is_bot_admin()
    async def reset_card(self, i: discord.Interaction, user: discord.Member):
        gid_str, uid_str = str(i.guild.id), str(user.id)
        if self.card_settings.get(gid_str, {}).pop(uid_str, None):
            await self._save_json(self.card_settings, self.card_settings_file)
        await i.response.send_message(PERSONALITY["card_reset"].format(user=user.mention), ephemeral=True)
        
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
        new_level = await self._add_xp(i.guild, user, -amount)
        await i.response.send_message(PERSONALITY["xp_removed"].format(amount=amount, user=user.mention, level=new_level), ephemeral=True)

    @admin_group.command(name="set-xp-rate", description="Set the min/max XP gained per message.")
    @app_commands.describe(min_xp="The minimum XP to grant.", max_xp="The maximum XP to grant.")
    @BotAdmin.is_bot_admin()
    async def set_xp_rate(self, i: discord.Interaction, min_xp: app_commands.Range[int, 1, 100], max_xp: app_commands.Range[int, 1, 200]):
        if min_xp >= max_xp: return await i.response.send_message("Min XP must be less than Max XP.", ephemeral=True)
        gid = str(i.guild.id); config = self.settings_data.setdefault(gid, {}).setdefault("leveling_config", {})
        config["min_xp"], config["max_xp"] = min_xp, max_xp
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