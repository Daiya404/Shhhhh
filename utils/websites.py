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
    # FIX: Renamed capture groups to be unique
    pattern = re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/(?P<twitter_username>[a-zA-Z0-9_]+)/status/(?P<twitter_post_id>[0-9]+)")
    
    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict()
        # FIX: Use the new unique group names
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
    # FIX: Renamed capture group to be unique
    pattern = re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels)/(?P<instagram_post_id>[a-zA-Z0-9_-]+)")

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        original_url = match.group(0)
        try:
            api_url = "https://embedez.com/api/v1/providers/combined"
            async with session.get(api_url, params={'q': original_url}, timeout=10) as response:
                if response.status != 200: return None
                api_data = await response.json()
                search_hash = api_data.get("data", {}).get("key")
                if not search_hash: return None
                return {
                    "display_name": cls.display_name,
                    "original_url": original_url,
                    "fixed_url": f"https://embedez.com/embed/{search_hash}",
                    "fixer_name": "EmbedEZ"
                }
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError):
            return None

class TikTok(Website):
    display_name = "TikTok"
    # FIX: Renamed capture groups to be unique
    pattern = re.compile(r"https?://(?:www\.)?tiktok\.com/(?:@(?P<tiktok_username>[a-zA-Z0-9_.]+)/video/(?P<tiktok_post_id>[0-9]+)|t/(?P<tiktok_short_id>\w+))")
    
    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict()
        original_url = match.group(0)
        fix_domain = "a.tnktok.com"

        # FIX: Use the new unique group names
        if data.get("tiktok_username") and data.get("tiktok_post_id"):
            username, post_id = data["tiktok_username"], data["tiktok_post_id"]
            return {"display_name": cls.display_name, "original_url": original_url, "fixed_url": f"https://{fix_domain}/@{username}/video/{post_id}", "profile_url": f"https://www.tiktok.com/@{username}", "author_name": f"@{username}"}
        elif data.get("tiktok_short_id"):
            return {"display_name": cls.display_name, "original_url": original_url, "fixed_url": f"https://{fix_domain}/t/{data['tiktok_short_id']}"}
        return None

class Reddit(Website):
    display_name = "Post"
    # FIX: Renamed capture groups to be unique
    pattern = re.compile(r"https?://(?:www\.)?reddit\.com/r/(?P<reddit_subreddit>\w+)/comments/(?P<reddit_post_id>\w+)(?:/(?P<reddit_slug>[^/?#]+))?/?")

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        # FIX: Use the new unique group names
        data = match.groupdict(); subreddit, post_id, slug = data.get("reddit_subreddit"), data.get("reddit_post_id"), data.get("reddit_slug")
        if not subreddit or not post_id: return None
        fixed_url = f"https://vxreddit.com/r/{subreddit}/comments/{post_id}"
        if slug: fixed_url += f"/{slug}"
        return {"display_name": cls.display_name, "original_url": match.group(0), "fixed_url": fixed_url, "profile_url": f"https://www.reddit.com/r/{subreddit}", "author_name": f"r/{subreddit}"}

class Pixiv(Website):
    display_name = "Artwork"
    # FIX: Renamed capture group to be unique
    pattern = re.compile(r"https?://(?:www\.)?pixiv\.net/(?:en/)?artworks/(?P<pixiv_post_id>[0-9]+)")

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        # FIX: Use the new unique group name
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