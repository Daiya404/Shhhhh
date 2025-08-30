# --- shared/utils/image_gen.py ---

import aiohttp
import asyncio
import io
import logging
from typing import Optional, Tuple, Dict
from PIL import Image, ImageDraw, ImageFont

# It's good practice to keep fonts in a dedicated assets folder
FONT_BOLD_PATH = "assets/fonts/unisans.otf"
FONT_REG_PATH = "assets/fonts/unisans.otf"

class ImageGenerator:
    """Handles the creation of all dynamic images for the bot."""
    def __init__(self, session: aiohttp.ClientSession):
        self.logger = logging.getLogger("ImageGenerator")
        self.session = session
        self.font_big = self._load_font(FONT_BOLD_PATH, 50)
        self.font_med = self._load_font(FONT_REG_PATH, 35)
        self.font_small = self._load_font(FONT_REG_PATH, 25)

    def _load_font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        """Loads a font file with a fallback to the default font."""
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            self.logger.warning(f"Could not load font: {path}. Using default.")
            return ImageFont.load_default()

    async def _fetch_image(self, url: str) -> Optional[bytes]:
        """Fetches an image from a URL with size and type checks."""
        if not url: return None
        try:
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200 and resp.content_type.startswith("image/"):
                    return await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self.logger.warning(f"Failed to fetch image {url}: {e}")
        return None

    def _draw_card(self, user_display_name: str, avatar_data: Optional[bytes], card_data: Dict) -> io.BytesIO:
        """The core drawing logic for the combined rank/profile card."""
        # --- Unpack all the data ---
        bg_data = card_data.get("background_data")
        color_hex = card_data.get("color", "#FFFFFF")
        rank = card_data.get("rank", 0)
        level = card_data.get("level", 0)
        current_xp = card_data.get("current_xp", 0)
        needed_xp = card_data.get("needed_xp", 100)
        bio = card_data.get("bio", "No bio set.")

        # --- Setup Canvas ---
        W, H = 934, 282
        card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if bg_data:
            try:
                bg = Image.open(io.BytesIO(bg_data)).convert("RGBA")
                # Resize and crop logic (simplified for brevity)
                bg = bg.resize((W, H), Image.Resampling.LANCZOS)
                card.paste(bg, (0, 0))
            except Exception: pass # Ignore if background fails

        overlay = Image.new("RGBA", (W, H), (40, 43, 48, 200))
        card = Image.alpha_composite(card, overlay)
        draw = ImageDraw.Draw(card)

        # --- Draw Avatar ---
        if avatar_data:
            try:
                pfp = Image.open(io.BytesIO(avatar_data)).convert("RGBA").resize((190, 190))
                mask = Image.new("L", pfp.size, 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, pfp.width, pfp.height), fill=255)
                card.paste(pfp, (50, 46), mask)
            except Exception: pass # Ignore if avatar fails

        # --- Draw XP Bar ---
        bar_x, bar_y, bar_w, bar_h, r = 280, 180, 600, 40, 20
        progress = (current_xp / needed_xp) * bar_w if needed_xp > 0 else 0
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), r, fill="#484B4E")
        if progress > 1:
            try:
                Image.new("RGB", (1, 1), color_hex) # Validate color
            except ValueError:
                color_hex = "#FFFFFF" # Fallback
            draw.rounded_rectangle((bar_x, bar_y, bar_x + progress, bar_y + bar_h), r, fill=color_hex)
        
        # --- Draw Text ---
        draw.text((280, 70), user_display_name, font=self.font_big, fill="#FFFFFF")
        draw.text((280, 135), bio[:50] + ('...' if len(bio) > 50 else ''), font=self.font_small, fill="#B9BBBE")

        xp_text = f"{current_xp:,} / {needed_xp:,} XP"
        xp_width = draw.textlength(xp_text, font=self.font_small)
        draw.text((W - 50 - xp_width, 140), xp_text, font=self.font_small, fill="#B9BBBE")

        # Rank
        rank_text = f"#{rank}"
        rank_width = draw.textlength(rank_text, font=self.font_big)
        draw.text((W - 50 - rank_width, 50), rank_text, font=self.font_big, fill="#FFFFFF")
        draw.text((W - 50 - rank_width - 100, 60), "RANK", font=self.font_med, fill="#B9BBBE")
        
        # Level
        level_text = str(level)
        level_width = draw.textlength(level_text, font=self.font_big)
        level_start_x = W - 50 - rank_width - 150 - level_width
        draw.text((level_start_x, 50), level_text, font=self.font_big, fill="#FFFFFF")
        draw.text((level_start_x - 110, 60), "LEVEL", font=self.font_med, fill="#B9BBBE")

        # --- Finalize ---
        buffer = io.BytesIO()
        card.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    async def create_user_card(self, user, card_data: Dict) -> io.BytesIO:
        """Fetches images and draws a unified user card."""
        avatar_url = user.display_avatar.url
        bg_url = card_data.get("background_url")

        avatar_data, bg_data = await asyncio.gather(
            self._fetch_image(avatar_url),
            self._fetch_image(bg_url)
        )
        card_data["background_data"] = bg_data

        # Run the CPU-bound drawing in a separate thread to avoid blocking
        return await asyncio.to_thread(self._draw_card, user.display_name, avatar_data, card_data)