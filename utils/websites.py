# utils/websites.py
import re
from abc import ABC, abstractmethod
from typing import Optional, Dict
import aiohttp
import asyncio
import logging

logger = logging.getLogger(__name__)

class Website(ABC):
    """
    Abstract base class defining the contract for fixable websites.
    
    Subclasses must implement:
    - display_name: Human-readable name for the content type
    - pattern: Compiled regex pattern to match URLs
    - get_links: Async method to extract and fix the link
    """
    display_name: str
    pattern: re.Pattern

    @classmethod
    @abstractmethod
    async def get_links(
        cls, 
        match: re.Match, 
        session: aiohttp.ClientSession
    ) -> Optional[Dict[str, str]]:
        """
        Extract link information from a regex match.
        
        Args:
            match: Regex match object containing URL components
            session: aiohttp session for making requests if needed
            
        Returns:
            Dictionary with keys:
                - display_name: Content type (e.g., "Tweet", "Post")
                - original_url: The original matched URL
                - fixed_url: The embed-friendly URL
                - author_name: (Optional) Username or author
                - profile_url: (Optional) Link to author's profile
                - fixer_name: (Optional) Name of the fixing service
            Returns None if the link cannot be processed.
        """
        pass

    @classmethod
    def _safe_extract_groups(cls, match: re.Match, *keys: str) -> tuple:
        """
        Safely extract named groups from a regex match.
        
        Args:
            match: Regex match object
            *keys: Named group keys to extract
            
        Returns:
            Tuple of extracted values (None for missing keys)
        """
        data = match.groupdict()
        return tuple(data.get(key) for key in keys)

# --- Define all supported websites here ---

class Twitter(Website):
    """
    Fix Twitter/X.com links using fxtwitter.
    
    Handles URLs from both twitter.com and x.com domains,
    including various subdomains (www, mobile, etc.)
    """
    display_name = "Tweet"
    pattern = re.compile(
        r"https?://(?:[\w-]+\.)?(?:twitter|x)\.com/"
        r"(?P<twitter_username>[a-zA-Z0-9_]+)/"
        r"status/(?P<twitter_post_id>[0-9]+)",
        re.IGNORECASE
    )
    
    @classmethod
    async def get_links(
        cls, 
        match: re.Match, 
        session: aiohttp.ClientSession
    ) -> Optional[Dict[str, str]]:
        username, post_id = cls._safe_extract_groups(
            match, "twitter_username", "twitter_post_id"
        )
        
        if not username or not post_id:
            logger.warning("Twitter URL missing username or post ID")
            return None
            
        return {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "fixed_url": f"https://fxtwitter.com/{username}/status/{post_id}",
            "profile_url": f"https://twitter.com/{username}",
            "author_name": username
        }

class Instagram(Website):
    """
    Fix Instagram links using d.vxinstagram.
    
    Supports posts, reels, and all Instagram content types.
    Handles various subdomains.
    """
    display_name = "Instagram"
    pattern = re.compile(
        r"https?://(?:[\w-]+\.)?instagram\.com/"
        r"(?P<instagram_path>p|reel|reels)/(?P<instagram_post_id>[a-zA-Z0-9_-]+)",
        re.IGNORECASE
    )

    @classmethod
    async def get_links(
        cls, 
        match: re.Match, 
        session: aiohttp.ClientSession
    ) -> Optional[Dict[str, str]]:
        path, post_id = cls._safe_extract_groups(
            match, "instagram_path", "instagram_post_id"
        )
        
        if not path or not post_id:
            logger.warning("Instagram URL missing path or post ID")
            return None
            
        return {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "fixed_url": f"https://d.vxinstagram.com/{path}/{post_id}",
            "fixer_name": "vxinstagram"
        }

class TikTok(Website):
    """
    Fix TikTok links using vxtiktok.
    
    Supports multiple URL formats:
    - Full format: tiktok.com/@user/video/123
    - Short links: tiktok.com/t/ABC or vm.tiktok.com/ABC
    - Video pages: tiktok.com/v/123.html
    """
    display_name = "TikTok"
    pattern = re.compile(
        r"https?://(?:[\w-]+\.)?tiktok\.com/"
        r"(?:"
        # Full link: @user/video|photo/123...
        r"(?:@(?P<tiktok_username>[\w\-\.]+)/(?:video|photo)/(?P<tiktok_post_id>\d+))"
        r"|"
        # Short links: /t/ABC, /ABC, /v/123.html
        r"(?:(?:t/|v/)?(?P<tiktok_short_id>[\w\d]+))"
        r")",
        re.IGNORECASE
    )

    @classmethod
    async def get_links(
        cls, 
        match: re.Match, 
        session: aiohttp.ClientSession
    ) -> Optional[Dict[str, str]]:
        username, post_id, short_id = cls._safe_extract_groups(
            match, "tiktok_username", "tiktok_post_id", "tiktok_short_id"
        )
        
        original_url = match.group(0)
        fix_domain = "vxtiktok.com"

        # Full URL format with username
        if username and post_id:
            return {
                "display_name": cls.display_name,
                "original_url": original_url,
                "fixed_url": f"https://{fix_domain}/@{username}/video/{post_id}",
                "profile_url": f"https://www.tiktok.com/@{username}",
                "author_name": f"@{username}"
            }
        
        # Short URL format
        elif short_id:
            return {
                "display_name": cls.display_name,
                "original_url": original_url,
                "fixed_url": f"https://{fix_domain}/t/{short_id}"
            }
        
        logger.warning("TikTok URL matched pattern but no valid groups found")
        return None

class Reddit(Website):
    """
    Fix Reddit links using rxddit.
    
    Supports both regular post URLs and short share links.
    Handles various subdomains (www, old, new, etc.)
    """
    display_name = "Post"
    pattern = re.compile(
        r"https?://(?:[\w-]+\.)?reddit\.com/"
        r"r/(?P<reddit_subreddit>\w+)/"
        r"(?:"
        r"comments/(?P<reddit_post_id>\w+)(?:/\S*)?"  # Full post URL
        r"|"
        r"s/(?P<reddit_share_id>\w+)"  # Short share URL
        r")",
        re.IGNORECASE
    )

    @classmethod
    async def get_links(
        cls, 
        match: re.Match, 
        session: aiohttp.ClientSession
    ) -> Optional[Dict[str, str]]:
        subreddit, post_id, share_id = cls._safe_extract_groups(
            match, "reddit_subreddit", "reddit_post_id", "reddit_share_id"
        )
        
        if not subreddit:
            logger.warning("Reddit URL missing subreddit")
            return None
        
        fix_domain = "rxddit.com"
        base_info = {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "profile_url": f"https://www.reddit.com/r/{subreddit}",
            "author_name": f"r/{subreddit}"
        }

        # Full post URL
        if post_id:
            base_info["fixed_url"] = (
                f"https://{fix_domain}/r/{subreddit}/comments/{post_id}"
            )
            return base_info
        
        # Short share URL
        elif share_id:
            base_info["fixed_url"] = f"https://{fix_domain}/r/{subreddit}/s/{share_id}"
            return base_info
        
        logger.warning("Reddit URL matched pattern but no post ID or share ID found")
        return None

class Pixiv(Website):
    """
    Fix Pixiv artwork links using phixiv.
    
    Supports both English and Japanese artwork URLs.
    """
    display_name = "Artwork"
    pattern = re.compile(
        r"https?://(?:www\.)?pixiv\.net/"
        r"(?:en/)?artworks/(?P<pixiv_post_id>[0-9]+)",
        re.IGNORECASE
    )

    @classmethod
    async def get_links(
        cls, 
        match: re.Match, 
        session: aiohttp.ClientSession
    ) -> Optional[Dict[str, str]]:
        post_id = cls._safe_extract_groups(match, "pixiv_post_id")[0]
        
        if not post_id:
            logger.warning("Pixiv URL missing post ID")
            return None
            
        return {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "fixed_url": f"https://phixiv.net/artworks/{post_id}"
        }

class Bluesky(Website):
    """
    Fix Bluesky links using bskyx.
    
    Supports both profile.bsky.social and bsky.app domains.
    """
    display_name = "Post"
    pattern = re.compile(
        r"https?://(?:bsky\.app|(?:[\w-]+\.)?bsky\.social)/"
        r"profile/(?P<bluesky_handle>[\w\.\-:]+)/"
        r"post/(?P<bluesky_post_id>[a-zA-Z0-9]+)",
        re.IGNORECASE
    )

    @classmethod
    async def get_links(
        cls, 
        match: re.Match, 
        session: aiohttp.ClientSession
    ) -> Optional[Dict[str, str]]:
        handle, post_id = cls._safe_extract_groups(
            match, "bluesky_handle", "bluesky_post_id"
        )
        
        if not handle or not post_id:
            logger.warning("Bluesky URL missing handle or post ID")
            return None
            
        return {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "fixed_url": f"https://bskyx.app/profile/{handle}/post/{post_id}",
            "profile_url": f"https://bsky.app/profile/{handle}",
            "author_name": handle
        }

# --- Master list of all available website fixers ---
all_websites = {
    "twitter": Twitter,
    "tiktok": TikTok,
    "instagram": Instagram,
    "reddit": Reddit,
    "pixiv": Pixiv,
    "bluesky": Bluesky,
}