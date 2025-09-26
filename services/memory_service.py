# services/memory_service.py
import logging
from typing import Dict, List
import asyncio
from collections import defaultdict

# Forward-declare for type hinting
if False:
    from services.data_manager import DataManager

class MemoryService:
    def __init__(self, data_manager: 'DataManager'):
        self.logger = logging.getLogger(__name__)
        self.data_manager = data_manager
        self.memory_cache: Dict[str, Dict[str, List[str]]] = {} # {guild_id: {user_id: [memory1, memory2]}}

        self._is_dirty = asyncio.Event()
        self._save_lock = asyncio.Lock()
        self.save_task: asyncio.Task = asyncio.create_task(self._periodic_save())

    async def on_ready(self):
        """Loads the user memories into the cache on startup."""
        self.memory_cache = await self.data_manager.get_data("user_memories")
        self.logger.info("User memory cache is ready.")

    async def _periodic_save(self):
        """Background task to save memories to disk only when they have changed."""
        while True:
            try:
                await self._is_dirty.wait()
                await asyncio.sleep(60) # Wait 60 seconds after a change to batch saves
                async with self._save_lock:
                    await self.data_manager.save_data("user_memories", self.memory_cache)
                    self._is_dirty.clear()
                    self.logger.info("Periodically saved user memories.")
            except asyncio.CancelledError:
                self.logger.info("Memory save task cancelled.")
                break
            except Exception as e:
                self.logger.error(f"Error in memory periodic save task: {e}", exc_info=True)
                await asyncio.sleep(120)

    async def add_memory(self, guild_id: int, user_id: int, memory: str):
        """Adds a new memory for a user and triggers a save."""
        guild_memories = self.memory_cache.setdefault(str(guild_id), {})
        user_memories = guild_memories.setdefault(str(user_id), [])
        
        # Avoid duplicate memories
        if memory not in user_memories:
            user_memories.append(memory)
            # Keep memory list from getting too long (e.g., last 20 facts)
            if len(user_memories) > 20:
                user_memories.pop(0)
            self._is_dirty.set()
            self.logger.info(f"Added new memory for user {user_id}: '{memory}'")

    def get_memories_for_user(self, guild_id: int, user_id: int) -> List[str]:
        """Retrieves all memories for a specific user."""
        return self.memory_cache.get(str(guild_id), {}).get(str(user_id), [])

    def cog_unload(self):
        """Cleanly shut down the save task."""
        self.save_task.cancel()