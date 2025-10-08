# services/data_manager.py
import json
import asyncio
import aiofiles
import logging # Import logging
from pathlib import Path
from collections import defaultdict

# Get a logger for this specific service
logger = logging.getLogger(__name__)
FILE_LOCKS = defaultdict(asyncio.Lock)

class DataManager:
    """Manages all data reading and writing to JSON files asynchronously."""

    def __init__(self, data_directory: Path):
        self.data_directory = data_directory

    async def get_data(self, filename: str) -> dict:
        """
        Asynchronously reads data from a JSON file.
        Returns an empty dictionary if the file doesn't exist or is invalid.
        """
        file_path = self.data_directory / f"{filename}.json"
        if not file_path.exists():
            return {}

        async with FILE_LOCKS[filename]:
            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    return json.loads(content) if content else {}
            except json.JSONDecodeError:
                # Log the error with personality
                logger.warning(f"Couldn't parse '{filename}.json'. It's likely empty or corrupted. Starting fresh.")
                return {}
            except Exception as e:
                logger.error(f"An unexpected error occurred while reading '{filename}.json': {e}")
                return {}

    async def save_data(self, filename: str, data: dict):
        """Asynchronously saves data to a JSON file."""
        file_path = self.data_directory / f"{filename}.json"
        async with FILE_LOCKS[filename]:
            try:
                async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(data, indent=2))
            except Exception as e:
                logger.error(f"Hmph. Failed to write to '{filename}.json'. Details: {e}")