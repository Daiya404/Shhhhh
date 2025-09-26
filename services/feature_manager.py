# services/feature_manager.py
from typing import Dict, List, Set
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class FeatureManager:
    """Manages feature enablement per guild with smart defaults."""
    
    def __init__(self, bot):
        self.bot = bot
        # Structure: {guild_id: {disabled_features}}
        self._config_cache: Dict[int, Set[str]] = {}
        self.available_features = self._discover_features()
        self.data_key = "server_configs"
    
    def _discover_features(self) -> List[str]:
        """Automatically discover available features from cogs directory."""
        cogs_dir = Path("cogs")
        if not cogs_dir.exists():
            return []
        
        features = []
        for cog_file in cogs_dir.glob("*.py"):
            if not cog_file.name.startswith("_"):
                feature_name = cog_file.stem
                features.append(feature_name)
        
        logger.info(f"Discovered features: {features}")
        return features
    
    async def load_cache(self):
        """Load server feature configurations from storage."""
        try:
            config_data = await self.bot.data_manager.get_data(self.data_key)
            self._config_cache = {
                int(guild_id): set(config.get("disabled_features", []))
                for guild_id, config in config_data.items()
            }
            logger.info(f"Loaded feature configs for {len(self._config_cache)} guilds")
        except Exception as e:
            logger.error(f"Error loading feature cache: {e}")
            self._config_cache = {}
    
    async def is_enabled(self, guild_id: int, feature_name: str) -> bool:
        """Check if a feature is enabled for a guild."""
        if feature_name not in self.available_features:
            return False
        
        disabled_features = self._config_cache.get(guild_id, set())
        return feature_name not in disabled_features
    
    async def enable_feature(self, guild_id: int, feature_name: str) -> bool:
        """Enable a feature. Returns True if state changed."""
        if feature_name not in self.available_features:
            raise ValueError(f"Unknown feature: {feature_name}")
        
        if guild_id not in self._config_cache:
            self._config_cache[guild_id] = set()
        
        if feature_name not in self._config_cache[guild_id]:
            return False  # Already enabled
        
        self._config_cache[guild_id].discard(feature_name)
        await self._save_to_storage()
        logger.info(f"Enabled feature '{feature_name}' for guild {guild_id}")
        return True
    
    async def disable_feature(self, guild_id: int, feature_name: str) -> bool:
        """Disable a feature. Returns True if state changed."""
        if feature_name not in self.available_features:
            raise ValueError(f"Unknown feature: {feature_name}")
        
        if guild_id not in self._config_cache:
            self._config_cache[guild_id] = set()
        
        if feature_name in self._config_cache[guild_id]:
            return False  # Already disabled
        
        self._config_cache[guild_id].add(feature_name)
        await self._save_to_storage()
        logger.info(f"Disabled feature '{feature_name}' for guild {guild_id}")
        return True
    
    async def get_feature_status(self, guild_id: int) -> Dict[str, bool]:
        """Get the status of all features for a guild."""
        return {
            feature: await self.is_enabled(guild_id, feature)
            for feature in self.available_features
        }
    
    async def reset_guild_features(self, guild_id: int):
        """Reset all features to default (enabled) for a guild."""
        if guild_id in self._config_cache:
            del self._config_cache[guild_id]
            await self._save_to_storage()
            logger.info(f"Reset features to default for guild {guild_id}")
    
    def refresh_available_features(self):
        """Refresh the list of available features."""
        self.available_features = self._discover_features()
    
    async def _save_to_storage(self):
        """Save feature configurations to storage."""
        try:
            storable_data = {}
            for guild_id, disabled_features in self._config_cache.items():
                if disabled_features:  # Only store if there are disabled features
                    storable_data[str(guild_id)] = {
                        "disabled_features": list(disabled_features)
                    }
            
            await self.bot.data_manager.save_data(self.data_key, storable_data)
        except Exception as e:
            logger.error(f"Error saving feature config: {e}")
            raise