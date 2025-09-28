import aiofiles
import asyncio
import json
import logging
from pathlib import Path
from collections import defaultdict

class DataManager:
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.data_dir = self.bot.root_dir / "data"
        self.data_dir.mkdir(exist_ok=True)
        self._locks = defaultdict(asyncio.Lock)

    async def get_data(self, filename: str) -> dict:
        """Asynchronously reads and returns data from a JSON file."""
        filepath = self.data_dir / f"{filename}.json"
        async with self._locks[filename]:
            if not filepath.exists():
                return {}
            try:
                async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f:
                    content = await f.read()
                    return json.loads(content) if content else {}
            except Exception as e:
                self.logger.error(f"Error reading {filepath}: {e}. Returning empty dictionary.")
                return {}

    async def save_data(self, filename: str, data: dict):
        """Asynchronously saves data to a JSON file."""
        filepath = self.data_dir / f"{filename}.json"
        async with self._locks[filename]:
            try:
                async with aiofiles.open(filepath, mode='w', encoding='utf-8') as f:
                    await f.write(json.dumps(data, indent=4))
            except Exception as e:
                self.logger.error(f"Could not save data to {filepath}: {e}")