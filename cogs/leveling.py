import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
import random
import time
from typing import Dict, Optional, Tuple
import asyncio
import io
import re

# Import the Pillow library for image manipulation
from PIL import Image, ImageDraw, ImageFont
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
    "card_reset": "Okay, I've reset the rank card customizations for {user}.",
    "font_error": "Could not load font file. Using default font instead.",
    "no_xp": "{user} hasn't earned any XP yet."
}

class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.session = aiohttp.ClientSession()
        
        # Ensure data directory exists
        Path("data").mkdir(exist_ok=True)
        
        self.settings_file = Path("data/role_settings.json")
        self.levels_file = Path("data/leveling_data.json")
        self.card_settings_file = Path("data/rank_card_settings.json")
        
        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        self.user_data: Dict[str, Dict] = self._load_json(self.levels_file)
        self.card_settings: Dict[str, Dict] = self._load_json(self.card_settings_file)
        self.cooldowns: Dict[int, Dict[int, float]] = {}
        
        # Cache for rank calculations to avoid repeated sorting
        self._rank_cache: Dict[str, Tuple[list, float]] = {}
        self._cache_expiry: float = 300  # 5 minutes

    async def cog_unload(self):
        await self.session.close()

    def _load_json(self, file_path: Path) -> Dict:
        """Load JSON file with error handling."""
        if not file_path.exists(): 
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f: 
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Error loading {file_path}: {e}")
            return {}

    async def _save_json(self, data: dict, file_path: Path):
        """Save JSON file with error handling."""
        try:
            file_path.parent.mkdir(exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f: 
                json.dump(data, f, indent=2)
        except IOError as e:
            self.logger.error(f"Error saving {file_path}: {e}")

    def _get_level_config(self, guild_id: int) -> Dict:
        """Get leveling configuration for a guild."""
        return self.settings_data.get(str(guild_id), {}).get("leveling_config", {
            "min_xp": 15, 
            "max_xp": 25, 
            "cooldown": 60
        })

    def _get_cached_ranks(self, guild_id: str) -> Optional[list]:
        """Get cached rank data if still valid."""
        if guild_id in self._rank_cache:
            ranks, timestamp = self._rank_cache[guild_id]
            if time.time() - timestamp < self._cache_expiry:
                return ranks
        return None

    def _update_rank_cache(self, guild_id: str, ranks: list):
        """Update the rank cache for a guild."""
        self._rank_cache[guild_id] = (ranks, time.time())

    # --- Core XP Logic ---
    async def process_xp(self, message: discord.Message):
        """Process XP gain for a message."""
        if not message.guild or message.author.bot: 
            return
        
        gid, uid = message.guild.id, message.author.id
        config = self._get_level_config(gid)
        now = time.time()
        
        self.cooldowns.setdefault(gid, {})
        if (now - self.cooldowns[gid].get(uid, 0)) < config["cooldown"]: 
            return
        
        self.cooldowns[gid][uid] = now
        xp_gain = random.randint(config["min_xp"], config["max_xp"])
        await self._add_xp(message.guild, message.author, xp_gain, message.channel)

    async def _add_xp(self, guild: discord.Guild, user: discord.Member, amount: int, channel: Optional[discord.TextChannel] = None):
        """Add XP to a user and handle level ups."""
        gid_str, uid_str = str(guild.id), str(user.id)
        self.user_data.setdefault(gid_str, {})
        user_level_data = self.user_data[gid_str].setdefault(uid_str, {"xp": 0, "level": 0})
        
        old_level = user_level_data["level"]
        user_level_data["xp"] = max(0, user_level_data["xp"] + amount)
        new_level = self._level_for_xp(user_level_data["xp"])
        
        if new_level != old_level:
            user_level_data["level"] = new_level
            # Clear rank cache when levels change
            if gid_str in self._rank_cache:
                del self._rank_cache[gid_str]
            
            if channel:
                await self._update_roles_for_level(guild, user, new_level, channel)
                if new_level > old_level:
                    await channel.send(PERSONALITY["level_up"].format(user=user.mention, level=new_level))
        
        await self._save_json(self.user_data, self.levels_file)
        return user_level_data["level"]

    def _xp_for_level(self, level: int) -> int:
        """Calculate XP required for a given level."""
        return 5 * (level ** 2) + 50 * level + 100

    def _level_for_xp(self, xp: int) -> int:
        """Calculate level for given XP using binary search for efficiency."""
        if xp < 100:  # Level 0
            return 0
        
        # Binary search for optimal performance
        low, high = 0, int((xp / 100) ** 0.5) + 10  # Rough upper bound
        
        while low < high:
            mid = (low + high + 1) // 2
            if self._xp_for_level(mid) <= xp:
                low = mid
            else:
                high = mid - 1
        
        return low

    async def _update_roles_for_level(self, guild: discord.Guild, user: discord.Member, new_level: int, channel: discord.TextChannel):
        """Update user roles based on new level."""
        level_roles_config = self.settings_data.get(str(guild.id), {}).get("level_roles", {})
        if not level_roles_config: 
            return
        
        level_roles = {int(k): v for k, v in level_roles_config.items()}
        highest_earned_role_id = None
        
        # Find highest level role the user qualifies for
        for level_tier in sorted(level_roles.keys(), reverse=True):
            if new_level >= level_tier: 
                highest_earned_role_id = level_roles[level_tier]
                break
        
        roles_to_add, roles_to_remove = set(), set()
        
        for level_tier, role_id in level_roles.items():
            role = guild.get_role(role_id)
            if not role: 
                continue
            
            if role_id == highest_earned_role_id:
                if role not in user.roles: 
                    roles_to_add.add(role)
            elif role in user.roles: 
                roles_to_remove.add(role)
        
        # Apply role changes
        try:
            if roles_to_add:
                await user.add_roles(*roles_to_add, reason="Leveling system reward")
                if channel: 
                    await channel.send(PERSONALITY["role_reward"].format(
                        level=new_level, 
                        role_name=list(roles_to_add)[0].name
                    ))
            
            if roles_to_remove: 
                await user.remove_roles(*roles_to_remove, reason="Leveling system role progression")
        except discord.Forbidden:
            self.logger.warning(f"Missing permissions to manage roles in guild {guild.id}")
        except discord.HTTPException as e:
            self.logger.error(f"Error updating roles: {e}")

    # --- Image Generation ---
    async def _generate_rank_card(self, user: discord.Member, rank: int, level: int, total_xp: int, current_xp: int, needed_xp: int) -> io.BytesIO:
        """Generate a rank card image."""
        gid_str, uid_str = str(user.guild.id), str(user.id)
        user_settings = self.card_settings.get(gid_str, {}).get(uid_str, {})
        bg_url = user_settings.get("background_url")
        color = user_settings.get("color", "#FFFFFF")
        
        avatar_data, bg_data = await self._fetch_card_images(user, bg_url)
        return await asyncio.to_thread(
            self._draw_card, 
            user, rank, level, total_xp, current_xp, needed_xp, 
            avatar_data, bg_data, color
        )

    async def _fetch_card_images(self, user: discord.Member, bg_url: Optional[str]) -> Tuple[Optional[bytes], Optional[bytes]]:
        """Fetch avatar and background images for rank card."""
        async def fetch(url):
            try:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200 and resp.content_length and resp.content_length < 10_000_000:  # 10MB limit
                        return await resp.read()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self.logger.warning(f"Failed to fetch image {url}: {e}")
            return None
        
        tasks = [fetch(str(user.display_avatar.with_size(256)))]
        if bg_url: 
            tasks.append(fetch(bg_url))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions in results
        avatar_data = results[0] if not isinstance(results[0], Exception) else None
        bg_data = None
        if bg_url and len(results) > 1:
            bg_data = results[1] if not isinstance(results[1], Exception) else None
        
        return avatar_data, bg_data

    def _draw_card(self, user, rank, level, total_xp, current_xp, needed_xp, avatar_data, bg_data, color_hex) -> io.BytesIO:
        """Draw the rank card using PIL."""
        W, H = 934, 282
        card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        
        # Handle background
        if bg_data:
            try:
                bg = Image.open(io.BytesIO(bg_data)).convert("RGBA")
                bg_w, bg_h = bg.size
                ratio = max(W / bg_w, H / bg_h)
                new_w, new_h = int(bg_w * ratio), int(bg_h * ratio)
                bg = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
                
                # Center crop
                left = (bg.width - W) // 2
                top = (bg.height - H) // 2
                bg = bg.crop((left, top, left + W, top + H))
                card.paste(bg, (0, 0))
            except Exception as e:
                self.logger.warning(f"Error processing background image: {e}")
        
        # Add overlay
        overlay = Image.new("RGBA", (W, H), (40, 43, 48, 200))
        card = Image.alpha_composite(card, overlay)
        draw = ImageDraw.Draw(card)
        
        # Load fonts with fallback
        try:
            font_big = ImageFont.truetype("assets/fonts/unisans.otf", 50)
            font_med = ImageFont.truetype("assets/fonts/unisans.otf", 35)
            font_small = ImageFont.truetype("assets/fonts/unisans.otf", 25)
        except (IOError, OSError):
            self.logger.warning(PERSONALITY["font_error"])
            # Fallback to default font
            font_big = ImageFont.load_default()
            font_med = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        # Draw avatar
        if avatar_data:
            try:
                pfp = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
                pfp = pfp.resize((190, 190), Image.Resampling.LANCZOS)
                
                # Create circular mask
                mask = Image.new("L", pfp.size, 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, pfp.width, pfp.height), fill=255)
                
                card.paste(pfp, (50, 46), mask)
            except Exception as e:
                self.logger.warning(f"Error processing avatar image: {e}")
        
        # Draw XP bar
        bar_x, bar_y, bar_w, bar_h, r = 280, 180, 600, 40, 20
        progress = (current_xp / needed_xp) * bar_w if needed_xp > 0 else 0
        
        # Background bar
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=r, fill="#484B4E")
        
        # Progress bar
        if progress > 0:
            # Validate color hex
            try:
                # Test if color is valid
                Image.new("RGB", (1, 1), color_hex)
                bar_color = color_hex
            except ValueError:
                bar_color = "#FFFFFF"  # Fallback color
            
            draw.rounded_rectangle((bar_x, bar_y, bar_x + progress, bar_y + bar_h), radius=r, fill=bar_color)
        
        # Draw text elements
        username = user.display_name if hasattr(user, 'display_name') else str(user)
        draw.text((280, 125), username, font=font_big, fill="#FFFFFF")
        
        # User discriminator (if exists)
        if hasattr(user, 'discriminator') and user.discriminator != "0":
            name_width = draw.textlength(username, font=font_big)
            draw.text((280 + name_width + 10, 140), f"#{user.discriminator}", font=font_small, fill="#B9BBBE")
        
        # XP text
        xp_text = f"{current_xp:,} / {needed_xp:,} XP"
        xp_bbox = draw.textbbox((0, 0), xp_text, font=font_small)
        xp_width = xp_bbox[2] - xp_bbox[0]
        draw.text((W - 50 - xp_width, 140), xp_text, font=font_small, fill="#B9BBBE")
        
        # Rank
        rank_text = f"#{rank}"
        rank_bbox = draw.textbbox((0, 0), rank_text, font=font_big)
        rank_width = rank_bbox[2] - rank_bbox[0]
        draw.text((W - 50 - rank_width, 50), rank_text, font=font_big, fill="#FFFFFF")
        
        # Rank label
        rank_label_bbox = draw.textbbox((0, 0), "RANK", font=font_med)
        rank_label_width = rank_label_bbox[2] - rank_label_bbox[0]
        draw.text((W - 50 - rank_width - 20 - rank_label_width, 60), "RANK", font=font_med, fill="#B9BBBE")
        
        # Level
        level_text = str(level)
        level_bbox = draw.textbbox((0, 0), level_text, font=font_big)
        level_width = level_bbox[2] - level_bbox[0]
        level_label_bbox = draw.textbbox((0, 0), "LEVEL", font=font_med)
        level_label_width = level_label_bbox[2] - level_label_bbox[0]
        
        level_start_x = W - 50 - rank_width - 20 - rank_label_width - 50 - level_width
        draw.text((level_start_x, 50), level_text, font=font_big, fill="#FFFFFF")
        draw.text((level_start_x - 20 - level_label_width, 60), "LEVEL", font=font_med, fill="#B9BBBE")
        
        # Save to buffer
        buffer = io.BytesIO()
        card.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    # --- User Commands ---
    @app_commands.command(name="rank", description="Check your or another user's level and rank.")
    @app_commands.describe(user="The user to check the rank of.")
    async def rank(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await interaction.response.defer()
        
        target = user or interaction.user
        gid, uid = str(interaction.guild.id), str(target.id)
        scores = self.user_data.get(gid, {})
        
        if not scores or uid not in scores:
            return await interaction.followup.send(PERSONALITY["no_xp"].format(user=target.display_name))
        
        # Use cached ranks if available
        sorted_users = self._get_cached_ranks(gid)
        if not sorted_users:
            sorted_users = sorted(scores.items(), key=lambda item: item[1]['xp'], reverse=True)
            self._update_rank_cache(gid, sorted_users)
        
        rank = next((r + 1 for r, (user_id, _) in enumerate(sorted_users) if user_id == uid), 0)
        
        user_data = scores[uid]
        xp, level = user_data["xp"], user_data["level"]
        xp_for_current = self._xp_for_level(level)
        xp_for_next = self._xp_for_level(level + 1)
        current_progress = xp - xp_for_current
        needed_progress = xp_for_next - xp_for_current
        
        try:
            card_buffer = await self._generate_rank_card(
                target, rank, level, xp, current_progress, needed_progress
            )
            file = discord.File(fp=card_buffer, filename="rank_card.png")
            await interaction.followup.send(file=file)
        except Exception as e:
            self.logger.error(f"Error generating rank card: {e}")
            # Fallback to text-based response
            embed = discord.Embed(
                title=f"{target.display_name}'s Rank",
                color=discord.Color.blue()
            )
            embed.add_field(name="Rank", value=f"#{rank}", inline=True)
            embed.add_field(name="Level", value=str(level), inline=True)
            embed.add_field(name="XP", value=f"{current_progress:,} / {needed_progress:,}", inline=True)
            embed.add_field(name="Total XP", value=f"{xp:,}", inline=False)
            await interaction.followup.send(embed=embed)
        
    @app_commands.command(name="leaderboard", description="Show the server's XP leaderboard.")
    @app_commands.describe(page="The page of the leaderboard to view.")
    async def leaderboard(self, interaction: discord.Interaction, page: app_commands.Range[int, 1, 100] = 1):
        gid = str(interaction.guild.id)
        scores = self.user_data.get(gid, {})
        
        if not scores:
            return await interaction.response.send_message("No one has earned any XP yet.", ephemeral=True)
        
        # Use cached ranks if available
        sorted_users = self._get_cached_ranks(gid)
        if not sorted_users:
            sorted_users = sorted(scores.items(), key=lambda item: item[1]['xp'], reverse=True)
            self._update_rank_cache(gid, sorted_users)
        
        total_pages = ((len(sorted_users) - 1) // 10) + 1
        if page > total_pages:
            page = total_pages
        
        embed = discord.Embed(title="🏆 Server Leaderboard", color=0xffd700)
        
        start, end = (page - 1) * 10, page * 10
        lb_text = ""
        
        for rank, (user_id, data) in enumerate(sorted_users[start:end], start=start + 1):
            user = self.bot.get_user(int(user_id))
            name = user.display_name if user else f"Unknown User"
            lb_text += f"**{rank}.** {name} - **Level {data['level']}** ({data['xp']:,} XP)\n"
        
        embed.description = lb_text or "No users on this page."
        embed.set_footer(text=f"Page {page}/{total_pages}")
        
        await interaction.response.send_message(embed=embed)

    # --- Card Customization Commands ---
    card_group = app_commands.Group(name="rank-card", description="Customize your personal rank card.")
    
    @card_group.command(name="set-background", description="Set a custom background image for your rank card.")
    @app_commands.describe(image_url="A direct link to an image (jpg, png, gif).")
    async def set_background(self, interaction: discord.Interaction, image_url: str):
        # Validate URL format
        if not re.match(r'https?://.+', image_url):
            return await interaction.response.send_message(PERSONALITY["bg_invalid"], ephemeral=True)
        
        try:
            async with self.session.head(image_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200 or not resp.content_type or not resp.content_type.startswith("image/"):
                    return await interaction.response.send_message(PERSONALITY["bg_invalid"], ephemeral=True)
                
                # Check file size
                if resp.content_length and resp.content_length > 10_000_000:  # 10MB limit
                    return await interaction.response.send_message("Image is too large (max 10MB).", ephemeral=True)
                    
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return await interaction.response.send_message(PERSONALITY["bg_invalid"], ephemeral=True)
        
        gid_str, uid_str = str(interaction.guild.id), str(interaction.user.id)
        self.card_settings.setdefault(gid_str, {}).setdefault(uid_str, {})["background_url"] = image_url
        await self._save_json(self.card_settings, self.card_settings_file)
        await interaction.response.send_message(PERSONALITY["bg_set"], ephemeral=True)

    @card_group.command(name="set-color", description="Set a custom accent color for your rank card.")
    @app_commands.describe(hex_code="The color in hex format (e.g., #A020F0).")
    async def set_color(self, interaction: discord.Interaction, hex_code: str):
        if not re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", hex_code):
            return await interaction.response.send_message(PERSONALITY["color_invalid"], ephemeral=True)
        
        gid_str, uid_str = str(interaction.guild.id), str(interaction.user.id)
        self.card_settings.setdefault(gid_str, {}).setdefault(uid_str, {})["color"] = hex_code
        await self._save_json(self.card_settings, self.card_settings_file)
        await interaction.response.send_message(PERSONALITY["color_set"].format(color=hex_code.upper()), ephemeral=True)

    @card_group.command(name="reset", description="[Admin] Reset a user's rank card customizations.")
    @app_commands.describe(user="The user whose card to reset.")
    @BotAdmin.is_bot_admin()
    async def reset_card(self, interaction: discord.Interaction, user: discord.Member):
        gid_str, uid_str = str(interaction.guild.id), str(user.id)
        if self.card_settings.get(gid_str, {}).pop(uid_str, None):
            await self._save_json(self.card_settings, self.card_settings_file)
        await interaction.response.send_message(PERSONALITY["card_reset"].format(user=user.mention), ephemeral=True)
        
    # --- Admin Commands ---
    admin_group = app_commands.Group(name="level-admin", description="Admin commands for the leveling system.")
    
    @admin_group.command(name="add-xp", description="Manually add XP to a user.")
    @app_commands.describe(user="The user to give XP to.", amount="The amount of XP to add.")
    @BotAdmin.is_bot_admin()
    async def add_xp(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]):
        new_level = await self._add_xp(interaction.guild, user, amount)
        await interaction.response.send_message(PERSONALITY["xp_added"].format(amount=amount, user=user.mention, level=new_level), ephemeral=True)

    @admin_group.command(name="remove-xp", description="Manually remove XP from a user.")
    @app_commands.describe(user="The user to take XP from.", amount="The amount of XP to remove.")
    @BotAdmin.is_bot_admin()
    async def remove_xp(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]):
        new_level = await self._add_xp(interaction.guild, user, -amount)
        await interaction.response.send_message(PERSONALITY["xp_removed"].format(amount=amount, user=user.mention, level=new_level), ephemeral=True)

    @admin_group.command(name="set-xp-rate", description="Set the min/max XP gained per message.")
    @app_commands.describe(min_xp="The minimum XP to grant.", max_xp="The maximum XP to grant.")
    @BotAdmin.is_bot_admin()
    async def set_xp_rate(self, interaction: discord.Interaction, min_xp: app_commands.Range[int, 1, 100], max_xp: app_commands.Range[int, 1, 200]):
        if min_xp >= max_xp:
            return await interaction.response.send_message("Min XP must be less than Max XP.", ephemeral=True)
        
        gid = str(interaction.guild.id)
        config = self.settings_data.setdefault(gid, {}).setdefault("leveling_config", {})
        config["min_xp"], config["max_xp"] = min_xp, max_xp
        await self._save_json(self.settings_data, self.settings_file)
        await interaction.response.send_message(PERSONALITY["settings_updated"], ephemeral=True)
        
    @admin_group.command(name="set-xp-cooldown", description="Set the cooldown between gaining XP.")
    @app_commands.describe(seconds="How many seconds a user must wait to get XP again.")
    @BotAdmin.is_bot_admin()
    async def set_xp_cooldown(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 5, 300]):
        gid = str(interaction.guild.id)
        config = self.settings_data.setdefault(gid, {}).setdefault("leveling_config", {})
        config["cooldown"] = seconds
        await self._save_json(self.settings_data, self.settings_file)
        await interaction.response.send_message(PERSONALITY["settings_updated"], ephemeral=True)
        
    @admin_group.command(name="set-level-role", description="Assign a role reward for reaching a specific level.")
    @app_commands.describe(level="The level to reward (must be a multiple of 10).", role="The role to grant.")
    @app_commands.choices(level=[app_commands.Choice(name=str(i), value=i) for i in range(10, 101, 10)])
    @BotAdmin.is_bot_admin()
    async def set_level_role(self, interaction: discord.Interaction, level: int, role: discord.Role):
        if role.position >= interaction.guild.me.top_role.position:
            return await interaction.response.send_message(
                "I cannot manage this role as it's higher than or equal to my highest role.", 
                ephemeral=True
            )
        
        gid = str(interaction.guild.id)
        level_roles = self.settings_data.setdefault(gid, {}).setdefault("level_roles", {})
        level_roles[str(level)] = role.id
        await self._save_json(self.settings_data, self.settings_file)
        await interaction.response.send_message(PERSONALITY["role_set"].format(level=level, role=role.mention), ephemeral=True)
        
    @admin_group.command(name="remove-level-role", description="Remove a role reward for a level.")
    @app_commands.describe(level="The level to remove the reward from.")
    @app_commands.choices(level=[app_commands.Choice(name=str(i), value=i) for i in range(10, 101, 10)])
    @BotAdmin.is_bot_admin()
    async def remove_level_role(self, interaction: discord.Interaction, level: int):
        gid = str(interaction.guild.id)
        level_roles = self.settings_data.setdefault(gid, {}).setdefault("level_roles", {})
        
        if str(level) in level_roles:
            del level_roles[str(level)]
            await self._save_json(self.settings_data, self.settings_file)
            # Clear rank cache since role configuration changed
            if gid in self._rank_cache:
                del self._rank_cache[gid]
        
        await interaction.response.send_message(PERSONALITY["role_unset"].format(level=level), ephemeral=True)
        
    @admin_group.command(name="view-roles", description="View the current level role configuration.")
    @BotAdmin.is_bot_admin()
    async def view_roles(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        level_roles = self.settings_data.get(gid, {}).get("level_roles", {})
        
        if not level_roles:
            return await interaction.response.send_message(PERSONALITY["no_roles_set"], ephemeral=True)
        
        embed = discord.Embed(title="Level Role Rewards", color=discord.Color.blue())
        desc = ""
        
        for level, role_id in sorted(level_roles.items(), key=lambda item: int(item[0])):
            role = interaction.guild.get_role(role_id)
            role_mention = role.mention if role else f"`Role Not Found (ID: {role_id})`"
            desc += f"**Level {level}:** {role_mention}\n"
        
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @admin_group.command(name="view-config", description="View the current leveling configuration.")
    @BotAdmin.is_bot_admin()
    async def view_config(self, interaction: discord.Interaction):
        config = self._get_level_config(interaction.guild.id)
        
        embed = discord.Embed(title="Leveling Configuration", color=discord.Color.green())
        embed.add_field(name="XP Range", value=f"{config['min_xp']} - {config['max_xp']} XP per message", inline=True)
        embed.add_field(name="Cooldown", value=f"{config['cooldown']} seconds", inline=True)
        
        # Add statistics
        gid = str(interaction.guild.id)
        if gid in self.user_data:
            total_users = len(self.user_data[gid])
            total_xp = sum(user['xp'] for user in self.user_data[gid].values())
            embed.add_field(name="Total Users", value=f"{total_users:,}", inline=True)
            embed.add_field(name="Total XP Earned", value=f"{total_xp:,}", inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @admin_group.command(name="reset-user", description="Reset a user's XP and level.")
    @app_commands.describe(user="The user to reset.")
    @BotAdmin.is_bot_admin()
    async def reset_user(self, interaction: discord.Interaction, user: discord.Member):
        gid_str, uid_str = str(interaction.guild.id), str(user.id)
        
        if gid_str in self.user_data and uid_str in self.user_data[gid_str]:
            del self.user_data[gid_str][uid_str]
            await self._save_json(self.user_data, self.levels_file)
            
            # Clear rank cache
            if gid_str in self._rank_cache:
                del self._rank_cache[gid_str]
            
            # Remove level roles
            level_roles_config = self.settings_data.get(gid_str, {}).get("level_roles", {})
            roles_to_remove = []
            for role_id in level_roles_config.values():
                role = interaction.guild.get_role(role_id)
                if role and role in user.roles:
                    roles_to_remove.append(role)
            
            if roles_to_remove:
                try:
                    await user.remove_roles(*roles_to_remove, reason="User XP reset by admin")
                except discord.Forbidden:
                    pass  # Ignore permission errors
        
        await interaction.response.send_message(f"Reset XP and level for {user.mention}.", ephemeral=True)
    
    @admin_group.command(name="import-mee6", description="Import levels from MEE6 (requires export file).")
    @app_commands.describe(
        attachment="JSON file exported from MEE6",
        overwrite="Whether to overwrite existing user data"
    )
    @BotAdmin.is_bot_admin()
    async def import_mee6(self, interaction: discord.Interaction, attachment: discord.Attachment, overwrite: bool = False):
        """Import user levels from a MEE6 export file."""
        if not attachment.filename.endswith('.json'):
            return await interaction.response.send_message("Please provide a JSON file.", ephemeral=True)
        
        if attachment.size > 5_000_000:  # 5MB limit
            return await interaction.response.send_message("File is too large (max 5MB).", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            data = await attachment.read()
            import_data = json.loads(data.decode('utf-8'))
            
            if not isinstance(import_data, dict) or 'users' not in import_data:
                return await interaction.followup.send("Invalid MEE6 export format.", ephemeral=True)
            
            gid_str = str(interaction.guild.id)
            self.user_data.setdefault(gid_str, {})
            imported_count = 0
            skipped_count = 0
            
            for user_data in import_data['users']:
                user_id = str(user_data.get('id', ''))
                xp = int(user_data.get('xp', 0))
                level = int(user_data.get('level', 0))
                
                if not user_id or xp < 0:
                    continue
                
                if user_id in self.user_data[gid_str] and not overwrite:
                    skipped_count += 1
                    continue
                
                # Convert MEE6 level to XP if needed
                if level > 0 and xp == 0:
                    xp = self._xp_for_level(level)
                
                self.user_data[gid_str][user_id] = {
                    "xp": xp,
                    "level": self._level_for_xp(xp)
                }
                imported_count += 1
            
            if imported_count > 0:
                await self._save_json(self.user_data, self.levels_file)
                # Clear rank cache
                if gid_str in self._rank_cache:
                    del self._rank_cache[gid_str]
            
            result_msg = f"Successfully imported {imported_count} users."
            if skipped_count > 0:
                result_msg += f" Skipped {skipped_count} existing users (use overwrite=True to replace)."
            
            await interaction.followup.send(result_msg, ephemeral=True)
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            await interaction.followup.send(f"Error parsing import file: {e}", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error importing MEE6 data: {e}")
            await interaction.followup.send("An error occurred during import.", ephemeral=True)
    
    # --- Event Listeners ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle XP processing for messages."""
        await self.process_xp(message)
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Optional: Clean up user data when member leaves (can be commented out to preserve data)."""
        # Uncomment the following lines if you want to delete user data when they leave
        # gid_str, uid_str = str(member.guild.id), str(member.id)
        # if gid_str in self.user_data and uid_str in self.user_data[gid_str]:
        #     del self.user_data[gid_str][uid_str]
        #     await self._save_json(self.user_data, self.levels_file)
        pass

async def setup(bot):
    """Setup function for loading the cog."""
    await bot.add_cog(Leveling(bot))