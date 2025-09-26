# services/data_manager.py
import aiofiles
import asyncio
import json
import os
from typing import Dict, Any

class DataManager:
    def __init__(self, data_folder="data"):
        self.data_path = data_folder
        self._locks: Dict[str, asyncio.Lock] = {}
        self._cache: Dict[str, Any] = {}

    async def init_path(self):
        """Ensure the data directory exists."""
        if not os.path.exists(self.data_path):
            os.makedirs(self.data_path)

    async def _get_lock(self, filename: str) -> asyncio.Lock:
        """Get or create a lock for a specific file."""
        if filename not in self._locks:
            self._locks[filename] = asyncio.Lock()
        return self._locks[filename]

    async def get_data(self, filename: str) -> Dict[str, Any]:
        """Asynchronously reads data from a JSON file. Uses cache if available."""
        if filename in self._cache:
            return self._cache[filename].copy()

        filepath = os.path.join(self.data_path, f"{filename}.json")
        lock = await self._get_lock(filename)
        
        async with lock:
            if not os.path.exists(filepath):
                return {}
            try:
                async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f:
                    content = await f.read()
                    data = json.loads(content)
                    self._cache[filename] = data
                    return data.copy()
            except (json.JSONDecodeError, FileNotFoundError):
                return {}

    async def save_data(self, filename: str, data: Dict[str, Any]):
        """Asynchronously saves data to a JSON file and updates the cache."""
        filepath = os.path.join(self.data_path, f"{filename}.json")
        lock = await self._get_lock(filename)
        
        async with lock:
            self._cache[filename] = data.copy()
            async with aiofiles.open(filepath, mode='w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=4))