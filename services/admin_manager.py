# services/admin_manager.py
from typing import Dict, Set

class AdminManager:
    def __init__(self, bot):
        self.bot = bot
        self._admin_cache: Dict[int, Set[int]] = {}

    async def load_cache(self):
        """Loads bot admin data from the data manager into the cache."""
        admin_data = await self.bot.data_manager.get_data("bot_admins")
        self._admin_cache = {int(guild_id): set(user_ids) for guild_id, user_ids in admin_data.items()}
        print("Admin cache loaded.")

    async def is_bot_admin(self, user) -> bool:
        """Checks if a user is a bot admin or server administrator."""
        # Server administrators are always bot admins
        if user.guild_permissions.administrator:
            return True
        
        # Fast cache lookup
        guild_admins = self._admin_cache.get(user.guild.id, set())
        return user.id in guild_admins

    def get_guild_admins(self, guild_id: int) -> Set[int]:
        """Gets the set of admin IDs for a guild."""
        return self._admin_cache.get(guild_id, set()).copy()

    async def add_admin(self, guild_id: int, user_id: int):
        """Adds a bot admin and updates both cache and storage."""
        if guild_id not in self._admin_cache:
            self._admin_cache[guild_id] = set()
        self._admin_cache[guild_id].add(user_id)
        await self._save_to_storage()

    async def remove_admin(self, guild_id: int, user_id: int):
        """Removes a bot admin."""
        if guild_id in self._admin_cache:
            self._admin_cache[guild_id].discard(user_id)
            if not self._admin_cache[guild_id]:
                del self._admin_cache[guild_id]
        await self._save_to_storage()
    
    async def _save_to_storage(self):
        """Saves the current state of the cache to the JSON file."""
        # Convert sets to lists for JSON serialization
        storable_data = {str(guild_id): list(user_ids) for guild_id, user_ids in self._admin_cache.items()}
        await self.bot.data_manager.save_data("bot_admins", storable_data)