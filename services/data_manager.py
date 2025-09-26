# services/data_manager.py
import aiofiles
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class DataManager:
    """Manages persistent data storage with caching and file locking."""
    
    def __init__(self, data_folder: str = "data"):
        self.data_path = Path(data_folder)
        self._locks: Dict[str, asyncio.Lock] = {}
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    async def init_path(self):
        """Ensure the data directory exists."""
        self.data_path.mkdir(exist_ok=True)
        logger.info(f"Data directory initialized: {self.data_path}")
    
    def _get_lock(self, filename: str) -> asyncio.Lock:
        """Get or create a lock for a specific file."""
        if filename not in self._locks:
            self._locks[filename] = asyncio.Lock()
        return self._locks[filename]
    
    def _get_filepath(self, filename: str) -> Path:
        """Get the full file path for a data file."""
        if not filename.endswith('.json'):
            filename += '.json'
        return self.data_path / filename
    
    async def get_data(self, filename: str, use_cache: bool = True) -> Dict[str, Any]:
        """Load data from a JSON file with optional caching."""
        if use_cache and filename in self._cache:
            return self._cache[filename].copy()
        
        filepath = self._get_filepath(filename)
        lock = self._get_lock(filename)
        
        async with lock:
            if not filepath.exists():
                return {}
            
            try:
                async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f:
                    content = await f.read()
                    data = json.loads(content) if content.strip() else {}
                    
                if use_cache:
                    self._cache[filename] = data.copy()
                
                return data
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error in {filepath}: {e}")
                return {}
            except Exception as e:
                logger.error(f"Error reading {filepath}: {e}")
                return {}
    
    async def save_data(self, filename: str, data: Dict[str, Any], update_cache: bool = True):
        """Save data to a JSON file with optional cache update."""
        filepath = self._get_filepath(filename)
        lock = self._get_lock(filename)
        
        async with lock:
            try:
                # Create backup if file exists
                if filepath.exists():
                    backup_path = filepath.with_suffix('.json.bak')
                    if backup_path.exists():
                        backup_path.unlink()
                    filepath.rename(backup_path)
                
                # Write new data
                async with aiofiles.open(filepath, mode='w', encoding='utf-8') as f:
                    await f.write(json.dumps(data, indent=2, ensure_ascii=False))
                
                if update_cache:
                    self._cache[filename] = data.copy()
                
                logger.debug(f"Saved data to {filepath}")
                
            except Exception as e:
                logger.error(f"Error saving {filepath}: {e}")
                # Restore backup if available
                backup_path = filepath.with_suffix('.json.bak')
                if backup_path.exists():
                    backup_path.rename(filepath)
                raise
    
    async def delete_data(self, filename: str):
        """Delete a data file and remove from cache."""
        filepath = self._get_filepath(filename)
        lock = self._get_lock(filename)
        
        async with lock:
            if filepath.exists():
                filepath.unlink()
            
            if filename in self._cache:
                del self._cache[filename]
    
    def clear_cache(self, filename: Optional[str] = None):
        """Clear cache for a specific file or all files."""
        if filename:
            self._cache.pop(filename, None)
        else:
            self._cache.clear()