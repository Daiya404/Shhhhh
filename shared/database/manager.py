import aiofiles
import json
import logging
from pathlib import Path
from typing import Dict, Any

class DataManager:
    """Unified, asynchronous data management with basic caching."""
    def __init__(self, base_path: str = "data"):
        self.logger = logging.getLogger("DataManager")
        self.base_path = Path(base_path)
        self.guilds_path = self.base_path / "guilds"
        self.users_path = self.base_path / "users"
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Create the base data directories if they don't exist."""
        self.base_path.mkdir(exist_ok=True)
        self.guilds_path.mkdir(exist_ok=True)
        self.users_path.mkdir(exist_ok=True)

    async def _load_json(self, path: Path) -> Dict[str, Any]:
        """Safely load a JSON file."""
        if not path.exists():
            return {}
        try:
            async with aiofiles.open(path, 'r', encoding='utf-8') as f:
                return json.loads(await f.read())
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Error loading JSON from {path}: {e}")
            return {}

    async def _save_json(self, path: Path, data: Dict[str, Any]):
        """Safely save a JSON file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=2, ensure_ascii=False))
        except IOError as e:
            self.logger.error(f"Error saving JSON to {path}: {e}")

    async def get_guild_data(self, guild_id: int, plugin_name: str) -> Dict[str, Any]:
        """Get all data for a specific plugin in a specific guild."""
        file_path = self.guilds_path / str(guild_id) / f"{plugin_name}.json"
        return await self._load_json(file_path)

    async def save_guild_data(self, guild_id: int, plugin_name: str, data: Dict[str, Any]):
        """Save data for a specific plugin in a specific guild."""
        file_path = self.guilds_path / str(guild_id) / f"{plugin_name}.json"
        await self._save_json(file_path, data)