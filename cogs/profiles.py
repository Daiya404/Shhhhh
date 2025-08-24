import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
import logging
from typing import Dict, Optional, Tuple
import asyncio
import io
from datetime import datetime

# Import the Pillow library for image manipulation
from PIL import Image, ImageDraw, ImageFont
import aiohttp

from .bot_admin import BotAdmin

# --- Personality Responses ---
PERSONALITY = {
    "profile_updated": "Fine, I've updated your profile. Try not to change it again five minutes from now.",
    "profile_no_data": "That user hasn't set up a profile yet. How lazy.",
    "profile_reset": "Done. The profile for {user} has been reset to its boring default state.",
    "invalid_date": "That's not a real date. I'm not stupid, you know. Use the format `DD MM YYYY`.",
    "text_too_long": "That's too long. I'm not writing a novel for you. Keep it under {limit} characters.",
    "font_error": "Could not load font file. Using default font instead.",
    "no_leveling_data": "No leveling data found for this user."
}

class Profiles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.session = aiohttp.ClientSession()
        
        # Ensure data directory exists
        Path("data").mkdir(exist_ok=True)
        
        self.profiles_file = Path("data/profiles.json")
        self.card_settings_file = Path("data/rank_card_settings.json")
        self.levels_file = Path("data/leveling_data.json")  # For XP data
        
        self.profile_data: Dict[str, Dict] = self._load_json(self.profiles_file)
        self.card_settings: Dict[str, Dict] = self._load_json(self.card_settings_file)
        self.user_data: Dict[str, Dict] = self._load_json(self.levels_file)  # For XP data

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

    def _xp_for_level(self, level: int) -> int:
        """Calculate XP required for a given level."""
        return 5 * (level ** 2) + 50 * level + 100

    def _get_user_xp_data(self, guild_id: str, user_id: str) -> Tuple[int, int, int, int, int]:
        """Get user's XP data for the progress bar."""
        user_level_data = self.user_data.get(guild_id, {}).get(user_id, {"xp": 0, "level": 0})
        
        total_xp = user_level_data["xp"]
        level = user_level_data["level"]
        xp_for_current = self._xp_for_level(level)
        xp_for_next = self._xp_for_level(level + 1)
        current_progress = total_xp - xp_for_current
        needed_progress = xp_for_next - xp_for_current
        
        return total_xp, level, current_progress, needed_progress, xp_for_next

    def _calculate_age(self, birthday_str: str) -> Optional[int]:
        """Calculate age from birthday string."""
        try:
            birthday = datetime.strptime(birthday_str, "%d/%m/%Y")
            today = datetime.now()
            age = today.year - birthday.year
            if today.month < birthday.month or (today.month == birthday.month and today.day < birthday.day):
                age -= 1
            return max(0, age)  # Ensure age is not negative
        except (ValueError, TypeError):
            return None

    # --- Image Generation ---
    async def _generate_profile_card(self, user: discord.Member) -> io.BytesIO:
        """Generate a profile card image with XP bar."""
        gid_str, uid_str = str(user.guild.id), str(user.id)
        
        # Get card customization settings
        card_config = self.card_settings.get(gid_str, {}).get(uid_str, {})
        bg_url = card_config.get("background_url")
        color = card_config.get("color", "#FFFFFF")

        # Get profile data
        profile_config = self.profile_data.get(gid_str, {}).get(uid_str, {})

        # Get XP data
        xp_data = self._get_user_xp_data(gid_str, uid_str)

        # Fetch images
        avatar_data, bg_data = await self._fetch_card_images(user, bg_url)
        
        return await asyncio.to_thread(
            self._draw_card, user, profile_config, xp_data, avatar_data, bg_data, color
        )

    async def _fetch_card_images(self, user: discord.Member, bg_url: Optional[str]) -> Tuple[Optional[bytes], Optional[bytes]]:
        """Fetch avatar and background images for profile card."""
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

    def _draw_card(self, user: discord.Member, profile_data: Dict, xp_data: Tuple, avatar_data, bg_data, color_hex) -> io.BytesIO:
        """Draw the profile card using PIL."""
        W, H = 1000, 400
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

        # Add overlay with slightly more transparency for profiles
        overlay = Image.new("RGBA", (W, H), (40, 43, 48, 210))
        card = Image.alpha_composite(card, overlay)
        draw = ImageDraw.Draw(card)
        
        # Load fonts with fallback
        try:
            font_bold = ImageFont.truetype("assets/fonts/unisans.otf", 42)
            font_reg = ImageFont.truetype("assets/fonts/unisans.otf", 32)
            font_small = ImageFont.truetype("assets/fonts/unisans.otf", 24)
            font_tiny = ImageFont.truetype("assets/fonts/unisans.otf", 18)
        except (IOError, OSError):
            self.logger.warning(PERSONALITY["font_error"])
            # Fallback to default font
            font_bold = ImageFont.load_default()
            font_reg = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_tiny = ImageFont.load_default()

        # Draw avatar
        if avatar_data:
            try:
                pfp = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
                pfp = pfp.resize((200, 200), Image.Resampling.LANCZOS)
                
                # Create circular mask
                mask = Image.new("L", pfp.size, 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, pfp.width, pfp.height), fill=255)
                
                card.paste(pfp, (50, 50), mask)
            except Exception as e:
                self.logger.warning(f"Error processing avatar image: {e}")

        # Draw username
        username = user.display_name if hasattr(user, 'display_name') else str(user)
        draw.text((280, 60), username, font=font_bold, fill="#FFFFFF")
        
        # Draw bio
        bio = profile_data.get("bio", "No bio set.")
        # Wrap bio text if it's too long
        if len(bio) > 60:
            bio = bio[:57] + "..."
        draw.text((280, 115), bio, font=font_small, fill="#B9BBBE")
        
        # Unpack XP data
        total_xp, level, current_progress, needed_progress, xp_for_next = xp_data
        
        # Draw XP Bar as separator (replacing the simple line)
        bar_x, bar_y, bar_w, bar_h, radius = 50, 270, W - 100, 20, 10
        
        # Background bar
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=radius, fill="#484B4E")
        
        # Progress bar
        if needed_progress > 0:
            progress = (current_progress / needed_progress) * bar_w
            if progress > 0:
                # Validate color hex
                try:
                    Image.new("RGB", (1, 1), color_hex)
                    bar_color = color_hex
                except ValueError:
                    bar_color = "#FFFFFF"  # Fallback color
                
                draw.rounded_rectangle((bar_x, bar_y, bar_x + progress, bar_y + bar_h), radius=radius, fill=bar_color)
        
        # Draw level and XP text on the bar
        level_text = f"Level {level}"
        xp_text = f"{current_progress:,} / {needed_progress:,} XP"
        
        # Position level text on the left side of the bar
        level_bbox = draw.textbbox((0, 0), level_text, font=font_tiny)
        level_width = level_bbox[2] - level_bbox[0]
        draw.text((bar_x + 10, bar_y - 20), level_text, font=font_tiny, fill="#FFFFFF")
        
        # Position XP text on the right side of the bar
        xp_bbox = draw.textbbox((0, 0), xp_text, font=font_tiny)
        xp_width = xp_bbox[2] - xp_bbox[0]
        draw.text((bar_x + bar_w - xp_width - 10, bar_y - 20), xp_text, font=font_tiny, fill="#B9BBBE")
        
        # Info Fields
        y_pos = 310
        
        # Calculate age
        age_str = "N/A"
        if "birthday" in profile_data:
            age = self._calculate_age(profile_data["birthday"])
            if age is not None:
                age_str = str(age)
        
        country = profile_data.get("country", "N/A")
        
        # Draw Age and Country
        draw.text((50, y_pos), "AGE", font=font_small, fill="#B9BBBE")
        draw.text((150, y_pos), age_str, font=font_reg, fill="#FFFFFF")
        draw.text((300, y_pos), "COUNTRY", font=font_small, fill="#B9BBBE")
        draw.text((450, y_pos), country, font=font_reg, fill="#FFFFFF")

        # Draw Favorite Game and Anime
        game = profile_data.get("game", "N/A")
        anime = profile_data.get("anime", "N/A")
        
        # Truncate long names to fit
        game_display = game[:25] + "..." if len(game) > 25 else game
        anime_display = anime[:25] + "..." if len(anime) > 25 else anime
        
        draw.text((50, y_pos + 40), "FAV GAME", font=font_small, fill="#B9BBBE")
        draw.text((180, y_pos + 40), game_display, font=font_reg, fill="#FFFFFF")
        draw.text((500, y_pos + 40), "FAV ANIME", font=font_small, fill="#B9BBBE")
        draw.text((650, y_pos + 40), anime_display, font=font_reg, fill="#FFFFFF")

        # Save to buffer
        buffer = io.BytesIO()
        card.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    # --- Command Groups ---
    profile_group = app_commands.Group(name="profile", description="Manage and view user profiles.")
    set_group = app_commands.Group(name="set", parent=profile_group, description="Set your profile information.")

    @profile_group.command(name="view", description="View your or another user's profile card.")
    @app_commands.describe(user="The user whose profile you want to see.")
    async def view_profile(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await interaction.response.defer()
        target = user or interaction.user
        
        # Check if user has any profile data OR leveling data
        gid_str, uid_str = str(interaction.guild.id), str(target.id)
        has_profile = bool(self.profile_data.get(gid_str, {}).get(uid_str))
        has_xp = bool(self.user_data.get(gid_str, {}).get(uid_str))
        
        if not has_profile and not has_xp:
            return await interaction.followup.send(PERSONALITY["profile_no_data"])
        
        try:
            card_buffer = await self._generate_profile_card(target)
            file = discord.File(fp=card_buffer, filename=f"profile_{target.id}.png")
            await interaction.followup.send(file=file)
        except Exception as e:
            self.logger.error(f"Error generating profile card: {e}")
            # Fallback to text-based response
            embed = discord.Embed(
                title=f"{target.display_name}'s Profile",
                color=discord.Color.blue()
            )
            
            profile_data = self.profile_data.get(gid_str, {}).get(uid_str, {})
            xp_data = self._get_user_xp_data(gid_str, uid_str)
            
            if profile_data.get("bio"):
                embed.add_field(name="Bio", value=profile_data["bio"], inline=False)
            
            if profile_data.get("birthday"):
                age = self._calculate_age(profile_data["birthday"])
                age_str = str(age) if age is not None else "N/A"
                embed.add_field(name="Age", value=age_str, inline=True)
            
            if profile_data.get("country"):
                embed.add_field(name="Country", value=profile_data["country"], inline=True)
            
            if profile_data.get("game"):
                embed.add_field(name="Favorite Game", value=profile_data["game"], inline=True)
            
            if profile_data.get("anime"):
                embed.add_field(name="Favorite Anime", value=profile_data["anime"], inline=True)
            
            # Add XP info
            total_xp, level, current_progress, needed_progress, _ = xp_data
            if total_xp > 0:
                embed.add_field(name="Level", value=str(level), inline=True)
                embed.add_field(name="XP Progress", value=f"{current_progress:,} / {needed_progress:,}", inline=True)
            
            await interaction.followup.send(embed=embed)

    @set_group.command(name="bio", description="Set your short bio.")
    @app_commands.describe(text="Your bio (max 100 characters).")
    async def set_bio(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 100]):
        # Sanitize input
        text = text.strip()
        if not text:
            return await interaction.response.send_message("Bio cannot be empty.", ephemeral=True)
        
        gid, uid = str(interaction.guild.id), str(interaction.user.id)
        self.profile_data.setdefault(gid, {}).setdefault(uid, {})["bio"] = text
        await self._save_json(self.profile_data, self.profiles_file)
        await interaction.response.send_message(PERSONALITY["profile_updated"], ephemeral=True)
        
    @set_group.command(name="birthday", description="Set your birthday to display your age.")
    @app_commands.describe(day="Day (DD)", month="Month (MM)", year="Year (YYYY).")
    async def set_birthday(self, interaction: discord.Interaction, 
                          day: app_commands.Range[int, 1, 31], 
                          month: app_commands.Range[int, 1, 12], 
                          year: app_commands.Range[int, 1900, 2024]):
        try:
            # Validate the date
            date_str = f"{day:02d}/{month:02d}/{year}"
            parsed_date = datetime.strptime(date_str, "%d/%m/%Y")
            
            # Check if the date is not in the future
            if parsed_date > datetime.now():
                return await interaction.response.send_message("Birthday cannot be in the future.", ephemeral=True)
            
            # Check for reasonable age limits (not older than 120 years)
            age = self._calculate_age(date_str)
            if age is not None and age > 120:
                return await interaction.response.send_message("Please enter a realistic birth year.", ephemeral=True)
                
        except ValueError:
            return await interaction.response.send_message(PERSONALITY["invalid_date"], ephemeral=True)
        
        gid, uid = str(interaction.guild.id), str(interaction.user.id)
        self.profile_data.setdefault(gid, {}).setdefault(uid, {})["birthday"] = date_str
        await self._save_json(self.profile_data, self.profiles_file)
        await interaction.response.send_message(PERSONALITY["profile_updated"], ephemeral=True)

    @set_group.command(name="country", description="Set your country.")
    @app_commands.describe(name="Your country's name (max 50 characters).")
    async def set_country(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 50]):
        # Sanitize input
        name = name.strip()
        if not name:
            return await interaction.response.send_message("Country cannot be empty.", ephemeral=True)
        
        gid, uid = str(interaction.guild.id), str(interaction.user.id)
        self.profile_data.setdefault(gid, {}).setdefault(uid, {})["country"] = name
        await self._save_json(self.profile_data, self.profiles_file)
        await interaction.response.send_message(PERSONALITY["profile_updated"], ephemeral=True)
        
    @set_group.command(name="game", description="Set your favorite game.")
    @app_commands.describe(name="Your favorite game (max 50 characters).")
    async def set_game(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 50]):
        # Sanitize input
        name = name.strip()
        if not name:
            return await interaction.response.send_message("Game cannot be empty.", ephemeral=True)
        
        gid, uid = str(interaction.guild.id), str(interaction.user.id)
        self.profile_data.setdefault(gid, {}).setdefault(uid, {})["game"] = name
        await self._save_json(self.profile_data, self.profiles_file)
        await interaction.response.send_message(PERSONALITY["profile_updated"], ephemeral=True)
        
    @set_group.command(name="anime", description="Set your favorite anime.")
    @app_commands.describe(name="Your favorite anime (max 50 characters).")
    async def set_anime(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 50]):
        # Sanitize input
        name = name.strip()
        if not name:
            return await interaction.response.send_message("Anime cannot be empty.", ephemeral=True)
        
        gid, uid = str(interaction.guild.id), str(interaction.user.id)
        self.profile_data.setdefault(gid, {}).setdefault(uid, {})["anime"] = name
        await self._save_json(self.profile_data, self.profiles_file)
        await interaction.response.send_message(PERSONALITY["profile_updated"], ephemeral=True)

    @profile_group.command(name="clear", description="Clear a specific field from your profile.")
    @app_commands.describe(field="The field to clear from your profile.")
    @app_commands.choices(field=[
        app_commands.Choice(name="Bio", value="bio"),
        app_commands.Choice(name="Birthday", value="birthday"),
        app_commands.Choice(name="Country", value="country"),
        app_commands.Choice(name="Favorite Game", value="game"),
        app_commands.Choice(name="Favorite Anime", value="anime")
    ])
    async def clear_field(self, interaction: discord.Interaction, field: str):
        gid, uid = str(interaction.guild.id), str(interaction.user.id)
        
        if gid not in self.profile_data or uid not in self.profile_data[gid]:
            return await interaction.response.send_message("You don't have a profile set up yet.", ephemeral=True)
        
        if field in self.profile_data[gid][uid]:
            del self.profile_data[gid][uid][field]
            await self._save_json(self.profile_data, self.profiles_file)
            await interaction.response.send_message(f"Cleared your {field} field.", ephemeral=True)
        else:
            await interaction.response.send_message(f"You don't have a {field} set.", ephemeral=True)
        
    @profile_group.command(name="reset", description="[Admin] Reset a user's profile information.")
    @app_commands.describe(user="The user whose profile to reset.")
    @BotAdmin.is_bot_admin()
    async def reset_profile(self, interaction: discord.Interaction, user: discord.Member):
        gid, uid = str(interaction.guild.id), str(user.id)
        if self.profile_data.get(gid, {}).pop(uid, None):
            await self._save_json(self.profile_data, self.profiles_file)
        await interaction.response.send_message(PERSONALITY["profile_reset"].format(user=user.mention), ephemeral=True)

    @profile_group.command(name="stats", description="[Admin] View profile system statistics.")
    @BotAdmin.is_bot_admin()
    async def profile_stats(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        profiles = self.profile_data.get(gid, {})
        
        if not profiles:
            return await interaction.response.send_message("No profiles have been created yet.", ephemeral=True)
        
        embed = discord.Embed(title="Profile System Statistics", color=discord.Color.green())
        embed.add_field(name="Total Profiles", value=str(len(profiles)), inline=True)
        
        # Count field usage
        field_counts = {"bio": 0, "birthday": 0, "country": 0, "game": 0, "anime": 0}
        for profile in profiles.values():
            for field in field_counts:
                if field in profile:
                    field_counts[field] += 1
        
        for field, count in field_counts.items():
            percentage = (count / len(profiles)) * 100 if profiles else 0
            embed.add_field(
                name=field.title(), 
                value=f"{count} ({percentage:.1f}%)", 
                inline=True
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    """Setup function for loading the cog."""
    await bot.add_cog(Profiles(bot))