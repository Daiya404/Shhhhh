# utils/websites.py
import re
from abc import ABC, abstractmethod
from typing import Optional, Dict
import aiohttp
import asyncio

class Website(ABC):
    """An abstract base class that defines the contract for a fixable website."""
    display_name: str
    pattern: re.Pattern

    @classmethod
    @abstractmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        """
        Takes a regex match and a session, and returns a dictionary with link data.
        Must be an async method.
        """
        pass

# --- Define all supported websites here ---

class Twitter(Website):
    display_name = "Tweet"
    pattern = re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/(?P<twitter_username>[a-zA-Z0-9_]+)/status/(?P<twitter_post_id>[0-9]+)")
    
    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict()
        username, post_id = data.get("twitter_username"), data.get("twitter_post_id")
        if not username or not post_id: return None
        return {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "fixed_url": f"https://fxtwitter.com/{username}/status/{post_id}",
            "profile_url": f"https://twitter.com/{username}",
            "author_name": username
        }

class Instagram(Website):
    display_name = "Instagram"
    pattern = re.compile(r"https?://(?:www\.)?instagram\.com/(?P<path>p|reel|reels)/(?P<instagram_post_id>[a-zA-Z0-9_-]+)")

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict()
        path = data.get("path")
        post_id = data.get("instagram_post_id")
        
        if not path or not post_id:
            return None

        # --- THIS IS THE CORRECTED PART ---
        # Uses the fixer from your image.
        return {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "fixed_url": f"https://d.vxinstagram.com/{path}/{post_id}",
            "fixer_name": "vxInstagram"
        }

class TikTok(Website):
    display_name = "TikTok"
    pattern = re.compile(r"https?://(?:www\.)?tiktok\.com/(?:@(?P<tiktok_username>[a-zA-Z0-9_.]+)/video/(?P<tiktok_post_id>[0-9]+)|t/(?P<tiktok_short_id>\w+))")
    
    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict()
        original_url = match.group(0)
        fix_domain = "a.tnktok.com"

        if data.get("tiktok_username") and data.get("tiktok_post_id"):
            username, post_id = data["tiktok_username"], data["tiktok_post_id"]
            return {"display_name": cls.display_name, "original_url": original_url, "fixed_url": f"https://{fix_domain}/@{username}/video/{post_id}", "profile_url": f"https://www.tiktok.com/@{username}", "author_name": f"@{username}"}
        elif data.get("tiktok_short_id"):
            return {"display_name": cls.display_name, "original_url": original_url, "fixed_url": f"https://{fix_domain}/t/{data['tiktok_short_id']}"}
        return None

class Reddit(Website):
    display_name = "Post"
    pattern = re.compile(r"https?://(?:www\.)?reddit\.com/r/(?P<reddit_subreddit>\w+)/(?:comments/(?P<reddit_post_id>\w+)(?:/(?P<reddit_slug>[^/?#]+))?|s/(?P<reddit_short_id>\w+))/?")

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict()
        subreddit = data.get("reddit_subreddit")
        if not subreddit:
            return None

        base_info = {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "profile_url": f"https://www.reddit.com/r/{subreddit}",
            "author_name": f"r/{subreddit}"
        }

        if post_id := data.get("reddit_post_id"):
            slug = data.get("reddit_slug")
            fixed_url = f"https://vxreddit.com/r/{subreddit}/comments/{post_id}"
            if slug:
                fixed_url += f"/{slug}"
            base_info["fixed_url"] = fixed_url
            return base_info
        elif short_id := data.get("reddit_short_id"):
            try:
                async with session.get(match.group(0), allow_redirects=False, timeout=10) as response:
                    if 300 <= response.status < 400 and 'Location' in response.headers:
                        redirect_url = response.headers['Location']
                        if 'reddit.com/r/' in redirect_url:
                            fixed_url = redirect_url.replace("reddit.com", "vxreddit.com", 1)
                            base_info["fixed_url"] = fixed_url
                            return base_info
                return None
            except (asyncio.TimeoutError, aiohttp.ClientError):
                return None

        return None

class Pixiv(Website):
    display_name = "Artwork"
    pattern = re.compile(r"https?://(?:www\.)?pixiv\.net/(?:en/)?artworks/(?P<pixiv_post_id>[0-9]+)")

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict(); post_id = data.get("pixiv_post_id")
        if not post_id: return None
        return {"display_name": cls.display_name, "original_url": match.group(0), "fixed_url": f"https://phixiv.net/artworks/{post_id}"}


# --- Master list of all available website fixers ---
all_websites = {
    "twitter": Twitter,
    "tiktok": TikTok,
    "instagram": Instagram,
    "reddit": Reddit,
    "pixiv": Pixiv,
}