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
    pattern = re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/(?P<username>[a-zA-Z0-9_]+)/status/(?P<post_id>[0-9]+)")
    
    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict()
        username, post_id = data.get("username"), data.get("post_id")
        if not username or not post_id: return None
        return {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "fixed_url": f"https://fxtwitter.com/{username}/status/{post_id}",
            "profile_url": f"https://twitter.com/{username}",
            "author_name": username
        }

# --- THE NEW API-BASED INSTAGRAM CLASS ---
class Instagram(Website):
    display_name = "Instagram"
    pattern = re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels)/(?P<post_id>[a-zA-Z0-9_-]+)")

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        original_url = match.group(0)
        
        try:
            # 1. Make an API call to EmbedEZ to get the real embed link.
            api_url = "https://embedez.com/api/v1/providers/combined"
            async with session.get(api_url, params={'q': original_url}, timeout=10) as response:
                if response.status != 200:
                    return None
                
                api_data = await response.json()
                search_hash = api_data.get("data", {}).get("key")
                if not search_hash:
                    return None

                # 2. Construct the final links using the API response.
                return {
                    "display_name": cls.display_name,
                    "original_url": original_url,
                    "fixed_url": f"https://embedez.com/embed/{search_hash}",
                    "fixer_name": "EmbedEZ" # This key signals the special message format
                }
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError):
            return None # If the API fails for any reason, we just fail silently.

class TikTok(Website):
    display_name = "TikTok"
    pattern = re.compile(r"https?://(?:www\.)?tiktok\.com/(?:@(?P<username>[a-zA-Z0-9_.]+)/video/(?P<post_id>[0-9]+)|t/(?P<short_id>\w+))")
    
    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict()
        original_url = match.group(0)
        fix_domain = "a.tnktok.com"

        if data.get("username") and data.get("post_id"):
            username, post_id = data["username"], data["post_id"]
            return {"display_name": cls.display_name, "original_url": original_url, "fixed_url": f"https://{fix_domain}/@{username}/video/{post_id}", "profile_url": f"https://www.tiktok.com/@{username}", "author_name": f"@{username}"}
        elif data.get("short_id"):
            return {"display_name": cls.display_name, "original_url": original_url, "fixed_url": f"https://{fix_domain}/t/{data['short_id']}"}
        return None

class Reddit(Website):
    display_name = "Post"
    pattern = re.compile(r"https?://(?:www\.)?reddit\.com/r/(?P<subreddit>\w+)/comments/(?P<post_id>\w+)(?:/(?P<slug>[^/?#]+))?/?")

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict(); subreddit, post_id, slug = data.get("subreddit"), data.get("post_id"), data.get("slug")
        if not subreddit or not post_id: return None
        fixed_url = f"https://vxreddit.com/r/{subreddit}/comments/{post_id}"
        if slug: fixed_url += f"/{slug}"
        return {"display_name": cls.display_name, "original_url": match.group(0), "fixed_url": fixed_url, "profile_url": f"https://www.reddit.com/r/{subreddit}", "author_name": f"r/{subreddit}"}

class Pixiv(Website):
    display_name = "Artwork"
    pattern = re.compile(r"https?://(?:www\.)?pixiv\.net/(?:en/)?artworks/(?P<post_id>[0-9]+)")

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        data = match.groupdict(); post_id = data.get("post_id")
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