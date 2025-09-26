# services/admin_manager.py
from typing import Dict, Set, List
import logging

logger = logging.getLogger(__name__)

class AdminManager:
    """Manages bot administrators with caching and persistence."""
    
    def __init__(self, bot):
        self.bot = bot
        self._admin_cache: Dict[int, Set[int]] = {}
        self.data_key = "bot_admins"
    
    async def load_cache(self):
        """Load bot admin data from storage into cache."""
        try:
            admin_data = await self.bot.data_manager.get_data(self.data_key)
            self._admin_cache = {
                int(guild_id): set(user_ids) 
                for guild_id, user_ids in admin_data.items()
            }
            logger.info(f"Loaded admin data for {len(self._admin_cache)} guilds")
        except Exception as e:
            logger.error(f"Error loading admin cache: {e}")
            self._admin_cache = {}
    
    async def is_bot_admin(self, user) -> bool:
        """Check if a user is a bot admin or server administrator."""
        # Guild owners and administrators are always admins
        if user.guild_permissions.administrator:
            return True
        
        # Check bot-specific admins
        guild_admins = self._admin_cache.get(user.guild.id, set())
        return user.id in guild_admins
    
    def get_guild_admins(self, guild_id: int) -> Set[int]:
        """Get all bot admin IDs for a guild."""
        return self._admin_cache.get(guild_id, set()).copy()
    
    async def add_admin(self, guild_id: int, user_id: int) -> bool:
        """Add a bot admin. Returns True if added, False if already admin."""
        if guild_id not in self._admin_cache:
            self._admin_cache[guild_id] = set()
        
        if user_id in self._admin_cache[guild_id]:
            return False
        
        self._admin_cache[guild_id].add(user_id)
        await self._save_to_storage()
        logger.info(f"Added admin {user_id} to guild {guild_id}")
        return True
    
    async def remove_admin(self, guild_id: int, user_id: int) -> bool:
        """Remove a bot admin. Returns True if removed, False if wasn't admin."""
        if guild_id not in self._admin_cache:
            return False
        
        if user_id not in self._admin_cache[guild_id]:
            return False
        
        self._admin_cache[guild_id].discard(user_id)
        
        # Clean up empty guild entries
        if not self._admin_cache[guild_id]:
            del self._admin_cache[guild_id]
        
        await self._save_to_storage()
        logger.info(f"Removed admin {user_id} from guild {guild_id}")
        return True
    
    async def get_all_admins(self, guild_id: int) -> List[int]:
        """Get all admin IDs for a guild as a list."""
        return list(self._admin_cache.get(guild_id, set()))
    
    async def _save_to_storage(self):
        """Save the current admin cache to storage."""
        try:
            # Convert sets to lists for JSON serialization
            storable_data = {
                str(guild_id): list(user_ids) 
                for guild_id, user_ids in self._admin_cache.items()
            }
            await self.bot.data_manager.save_data(self.data_key, storable_data)
        except Exception as e:
            logger.error(f"Error saving admin data: {e}")
            raise