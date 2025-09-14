# services/data_manager.py
import logging
import aiofiles
import json
from pathlib import Path
from typing import Dict, Any
from collections import defaultdict
import asyncio

FILE_LOCKS = defaultdict(asyncio.Lock)

class DataManager:
    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.cache = {}
        self.logger = logging.getLogger(__name__)

    async def _read_file(self, file_name: str) -> Dict:
        file_path = self.base_path / file_name
        if not file_path.exists():
            return {}

        async with FILE_LOCKS[file_name]:
            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    return json.loads(content) if content else {}
            except Exception as e:
                self.logger.error(f"Failed to read or parse {file_name}", exc_info=e)
                return {}

    async def _write_file(self, file_name: str, data: Dict):
        file_path = self.base_path / file_name
        async with FILE_LOCKS[file_name]:
            try:
                async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(data, indent=2, ensure_ascii=False))
                self.cache[file_name] = data # Update cache on successful write
            except Exception as e:
                self.logger.error(f"Failed to write to {file_name}", exc_info=e)

    async def get_data(self, data_type: str) -> Dict:
        """Gets the entire dataset for a type (e.g., 'bot_admins'). Uses cache."""
        file_name = f"{data_type}.json"
        if file_name in self.cache:
            return self.cache[file_name]
        
        data = await self._read_file(file_name)
        self.cache[file_name] = data
        return data

    async def save_data(self, data_type: str, data: Dict):
        """Saves the entire dataset for a type."""
        file_name = f"{data_type}.json"
        await self._write_file(file_name, data)