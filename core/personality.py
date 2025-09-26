import json
from pathlib import Path
from typing import Dict, Any, Optional

class PersonalityManager:
    """Manages bot personality responses and behavior patterns."""
    
    def __init__(self, personality_file: str = "assets/personality.json"):
        self.personality_file = Path(personality_file)
        self.personality_data = self._load_personality()
    
    def _load_personality(self) -> Dict[str, Any]:
        """Load personality data from file."""
        if not self.personality_file.exists():
            return self._get_default_personality()
        
        try:
            with open(self.personality_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return self._get_default_personality()
    
    def _get_default_personality(self) -> Dict[str, Any]:
        """Return default personality configuration."""
        return {
            "general": {
                "greeting": "What do you need?",
                "error": "Something went wrong. Don't expect me to fix it for you.",
                "permission_denied": "You don't have the authority to ask that of me.",
                "feature_disabled": "This feature is disabled for this server."
            },
            "admin": {
                "admin_added": "Fine, I'll acknowledge `{user}` now. Don't make me regret it.",
                "admin_removed": "Noted. `{user}` is no longer a bot admin.",
                "already_admin": "That person is already on the list. Pay attention.",
                "not_admin": "I wasn't listening to them anyway.",
                "list_admins_title": "Delegated Bot Admins",
                "no_admins": "No extra bot admins have been added. It's just the server administrators."
            },
            "feature": {
                "feature_enabled": "Hmph. The `{feature}` feature is now **enabled**.",
                "feature_disabled": "Alright, the `{feature}` feature has been **disabled**.",
                "already_enabled": "It's already enabled. Weren't you paying attention?",
                "already_disabled": "I already disabled it. Stop wasting my time.",
                "feature_not_found": "I don't know what `{feature}` is. Try a real one.",
                "list_features_title": "Feature Status"
            },
            "hello": {
                "response": "Hello. Don't get used to this.",
                "response_friend": "Oh, it's you. Hello, `{user}`."
            }
        }
    
    def get(self, category: str, key: str, **kwargs) -> str:
        """Get a personality response with optional formatting."""
        try:
            response = self.personality_data[category][key]
            return response.format(**kwargs) if kwargs else response
        except KeyError:
            return "I don't know what to say to that."
    
    def get_category(self, category: str) -> Dict[str, str]:
        """Get all responses from a category."""
        return self.personality_data.get(category, {})