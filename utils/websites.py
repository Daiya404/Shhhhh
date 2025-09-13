# utils/websites.py
import re
from abc import ABC, abstractmethod

class Website(ABC):
    """An abstract base class that defines the contract for a fixable website."""
    
    # A regex pattern that must contain one capturing group for the link's path/ID.
    # Example: r"https?://(?:www\.)?twitter\.com/([a-zA-Z0-9_]+/status/[0-9]+)"
    pattern: re.Pattern
    
    # The replacement domain.
    # Example: "fxtwitter.com"
    fix_domain: str

    @classmethod
    def match(cls, content: str) -> list[str]:
        """Finds all occurrences of this website's links in a message."""
        return cls.pattern.findall(content)

    @classmethod
    def fix(cls, match: str) -> str:
        """Takes a matched path/ID and returns the full, fixed URL."""
        return f"https://{cls.fix_domain}/{match}"

# --- Define all supported websites here ---

class Twitter(Website):
    pattern = re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/([a-zA-Z0-9_]+/status/[0-9]+)")
    fix_domain = "fxtwitter.com"

class Reddit(Website):
    pattern = re.compile(r"https?://(?:www\.)?reddit\.com/([a-zA-Z0-9_/]+comments/[a-zA-Z0-9_]+)")
    fix_domain = "vxreddit.com"
    
class TikTok(Website):
    pattern = re.compile(r"https?://(?:www\.)?(?:tiktok)\.com/([@a-zA-Z0-9_]+/video/[0-9]+)")
    fix_domain = "vxtiktok.com"

# --- Master list of all available website fixers ---
# To add a new site, just create a class above and add it to this list.
all_websites = {
    "twitter": Twitter,
    "reddit": Reddit,
    "tiktok": TikTok,
    # Add future classes here, e.g., "instagram": Instagram,
}