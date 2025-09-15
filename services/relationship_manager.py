# services/relationship_manager.py
import logging
import time
from typing import Dict, List, Tuple

class RelationshipManager:
    def __init__(self, data_manager):
        self.logger = logging.getLogger(__name__)
        self.data_manager = data_manager
        # In-memory cache for all user relationship data for instant access
        self.relationships_cache: Dict[str, Dict[str, Dict]] = {}

    async def on_ready(self):
        """Loads the user relationships into the cache on startup."""
        self.relationships_cache = await self.data_manager.get_data("user_relationships")
        self.logger.info("User relationship cache is ready.")

    async def _save_cache(self):
        """Saves the entire relationship cache back to the disk."""
        await self.data_manager.save_data("user_relationships", self.relationships_cache)

    def _get_user_profile(self, guild_id: int, user_id: int) -> Dict:
        """
        Safely gets a user's profile from the cache, creating a default one if it doesn't exist.
        """
        guild_profiles = self.relationships_cache.setdefault(str(guild_id), {})
        # Return a default profile for new users
        return guild_profiles.setdefault(str(user_id), {
            "interaction_count": 0,
            "last_seen_timestamp": 0,
            "recent_questions": []
        })

    # --- "Read" Methods: Used by the AI to understand the user ---

    def analyze_relationship(self, guild_id: int, user_id: int) -> str:
        """Determines the relationship level with a user based on interaction history."""
        profile = self._get_user_profile(guild_id, user_id)
        count = profile.get("interaction_count", 0)
        
        if count < 3:
            return "new_person"
        elif count < 15:
            return "acquaintance"
        else:
            return "close_friend"

    def detect_repeated_question(self, guild_id: int, user_id: int, message: str) -> Tuple[bool, List[str]]:
        """
        Checks if a user is asking a similar question again and updates their question history.
        Returns a tuple: (is_repeated, updated_question_history)
        """
        profile = self._get_user_profile(guild_id, user_id)
        recent_questions = profile.get("recent_questions", [])
        message_lower = message.lower()
        is_repeated = False

        for prev_question in recent_questions:
            # A simple but effective similarity check
            if any(word in message_lower for word in prev_question.split() if len(word) > 3):
                similarity = sum(1 for word in prev_question.split() if len(word) > 3 and word in message_lower)
                if similarity >= 2:
                    is_repeated = True
                    break
        
        recent_questions.append(message_lower)
        # Keep only the last 5 questions for checking
        if len(recent_questions) > 5:
            profile["recent_questions"] = recent_questions[-5:]
        else:
            profile["recent_questions"] = recent_questions
            
        return is_repeated, profile["recent_questions"]

    # --- "Write" Method: Used by the AI to update its memory ---

    async def record_interaction(self, guild_id: int, user_id: int):
        """Updates a user's profile after an interaction."""
        profile = self._get_user_profile(guild_id, user_id)
        profile["interaction_count"] += 1
        profile["last_seen_timestamp"] = int(time.time())
        # The question history is already updated by detect_repeated_question
        
        # Save the updated cache to disk
        await self._save_cache()