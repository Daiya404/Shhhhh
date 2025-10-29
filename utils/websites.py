# utils/websites.py
"""
Website link fixing utilities for social media embeds.

This module defines Website classes that convert standard social media URLs
into embed-friendly alternatives for better Discord integration.
"""

import re
from abc import ABC, abstractmethod
from typing import Optional, Dict
import aiohttp
import logging

logger = logging.getLogger(__name__)


class Website(ABC):
    """
    Abstract base class for fixable websites.
    
    Each subclass represents a social media platform and defines:
    - display_name: Human-readable content type (e.g., "Tweet", "Post")
    - pattern: Compiled regex to match URLs from that platform
    - get_links: Async method to transform URLs into embed-friendly versions
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
        Transform a matched URL into embed-friendly link data.
        
        Args:
            match: Regex match containing URL components
            session: aiohttp session for API requests (if needed)
            
        Returns:
            Dictionary containing:
                - display_name: Content type (e.g., "Tweet", "Post")
                - original_url: The matched URL
                - fixed_url: Embed-friendly URL
                - author_name: (Optional) Username/author
                - profile_url: (Optional) Author's profile link
                - fixer_name: (Optional) Embed service name
            Returns None if URL cannot be processed.
        """
        pass

    @classmethod
    def _safe_extract_groups(cls, match: re.Match, *keys: str) -> tuple:
        """
        Safely extract named groups from regex match.
        
        Args:
            match: Regex match object
            *keys: Named group keys to extract
            
        Returns:
            Tuple of values (None for missing keys)
        """
        data = match.groupdict()
        return tuple(data.get(key) for key in keys)

    @classmethod
    def _validate_required(cls, *values) -> bool:
        """Check if all required values are present."""
        return all(v is not None for v in values)


# ============================================================================
# Website Implementations
# ============================================================================

class Twitter(Website):
    """
    Twitter/X link fixer using fxtwitter.
    
    Supports: twitter.com and x.com (all subdomains)
    Example: twitter.com/user/status/123 → fxtwitter.com/user/status/123
    """
    display_name = "Tweet"
    pattern = re.compile(
        r"https?://(?:[\w-]+\.)?(?:twitter|x)\.com/"
        r"(?P<twitter_username>[a-zA-Z0-9_]+)/"
        r"status/(?P<twitter_post_id>[0-9]+)",
        re.IGNORECASE
    )
    
    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        username, post_id = cls._safe_extract_groups(match, "twitter_username", "twitter_post_id")
        
        if not cls._validate_required(username, post_id):
            logger.warning("Twitter URL missing required fields")
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
    Instagram link fixer using vxinstagram.
    
    Supports: Posts, reels, and all content types
    Example: instagram.com/p/ABC → d.vxinstagram.com/p/ABC
    """
    display_name = "Instagram"
    pattern = re.compile(
        r"https?://(?:[\w-]+\.)?instagram\.com/"
        r"(?P<instagram_path>p|reel|reels)/(?P<instagram_post_id>[a-zA-Z0-9_-]+)",
        re.IGNORECASE
    )

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        path, post_id = cls._safe_extract_groups(match, "instagram_path", "instagram_post_id")
        
        if not cls._validate_required(path, post_id):
            logger.warning("Instagram URL missing required fields")
            return None
            
        return {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "fixed_url": f"https://d.vxinstagram.com/{path}/{post_id}",
            "fixer_name": "vxinstagram"
        }


class TikTok(Website):
    """
    TikTok link fixer using vxtiktok.
    
    Supports multiple formats:
    - Full: tiktok.com/@user/video/123
    - Short: tiktok.com/t/ABC or vm.tiktok.com/ABC
    """
    display_name = "TikTok"
    pattern = re.compile(
        r"https?://(?:[\w-]+\.)?tiktok\.com/"
        r"(?:"
        r"(?:@(?P<tiktok_username>[\w\-\.]+)/(?:video|photo)/(?P<tiktok_post_id>\d+))"
        r"|"
        r"(?:(?:t/|v/)?(?P<tiktok_short_id>[\w\d]+))"
        r")",
        re.IGNORECASE
    )

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        username, post_id, short_id = cls._safe_extract_groups(
            match, "tiktok_username", "tiktok_post_id", "tiktok_short_id"
        )
        
        original_url = match.group(0)
        fix_domain = "vxtiktok.com"

        # Full URL with username
        if username and post_id:
            return {
                "display_name": cls.display_name,
                "original_url": original_url,
                "fixed_url": f"https://{fix_domain}/@{username}/video/{post_id}",
                "profile_url": f"https://www.tiktok.com/@{username}",
                "author_name": f"@{username}"
            }
        
        # Short URL
        if short_id:
            return {
                "display_name": cls.display_name,
                "original_url": original_url,
                "fixed_url": f"https://{fix_domain}/t/{short_id}"
            }
        
        logger.warning("TikTok URL matched but no valid groups found")
        return None


class Reddit(Website):
    """
    Reddit link fixer using rxddit.
    
    Supports:
    - Full post URLs: reddit.com/r/sub/comments/123/title
    - Share links: reddit.com/r/sub/s/ABC
    """
    display_name = "Post"
    pattern = re.compile(
        r"https?://(?:[\w-]+\.)?reddit\.com/"
        r"r/(?P<reddit_subreddit>\w+)/"
        r"(?:"
        r"comments/(?P<reddit_post_id>\w+)(?:/\S*)?"
        r"|"
        r"s/(?P<reddit_share_id>\w+)"
        r")",
        re.IGNORECASE
    )

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
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
            base_info["fixed_url"] = f"https://{fix_domain}/r/{subreddit}/comments/{post_id}"
            return base_info
        
        # Share link (includes subreddit in path)
        if share_id:
            base_info["fixed_url"] = f"https://{fix_domain}/r/{subreddit}/s/{share_id}"
            return base_info
        
        logger.warning("Reddit URL matched but missing post/share ID")
        return None


class Pixiv(Website):
    """
    Pixiv artwork fixer using phixiv.
    
    Supports both English and Japanese artwork URLs.
    Example: pixiv.net/artworks/123 → phixiv.net/artworks/123
    """
    display_name = "Artwork"
    pattern = re.compile(
        r"https?://(?:www\.)?pixiv\.net/"
        r"(?:en/)?artworks/(?P<pixiv_post_id>[0-9]+)",
        re.IGNORECASE
    )

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
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
    Bluesky link fixer using bskyx.
    
    Supports both bsky.app and bsky.social domains.
    Example: bsky.app/profile/user.bsky.social/post/ABC → bskyx.app/profile/user.bsky.social/post/ABC
    """
    display_name = "Post"
    pattern = re.compile(
        r"https?://(?:bsky\.app|(?:[\w-]+\.)?bsky\.social)/"
        r"profile/(?P<bluesky_handle>[\w\.\-:]+)/"
        r"post/(?P<bluesky_post_id>[a-zA-Z0-9]+)",
        re.IGNORECASE
    )

    @classmethod
    async def get_links(cls, match: re.Match, session: aiohttp.ClientSession) -> Optional[Dict[str, str]]:
        handle, post_id = cls._safe_extract_groups(match, "bluesky_handle", "bluesky_post_id")
        
        if not cls._validate_required(handle, post_id):
            logger.warning("Bluesky URL missing required fields")
            return None
            
        return {
            "display_name": cls.display_name,
            "original_url": match.group(0),
            "fixed_url": f"https://bskyx.app/profile/{handle}/post/{post_id}",
            "profile_url": f"https://bsky.app/profile/{handle}",
            "author_name": handle
        }


# ============================================================================
# Registry
# ============================================================================

# Master list of all available website fixers
all_websites = {
    "twitter": Twitter,
    "tiktok": TikTok,
    "instagram": Instagram,
    "reddit": Reddit,
    "pixiv": Pixiv,
    "bluesky": Bluesky,
}