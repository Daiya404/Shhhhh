# services/feature_manager.py
from typing import Dict, List, Set

class FeatureManager:
    def __init__(self, bot):
        self.bot = bot
        # Structure: {guild_id: {disabled_features_set}}
        self._config_cache: Dict[int, Set[str]] = {}
        # Get a list of available features from cog filenames
        self.available_features = self._get_available_features()

    def _get_available_features(self) -> List[str]:
        """Scans the cogs directory to find available features."""
        # NOTE: This assumes one cog file = one feature.
        # You can make this more granular later if needed.
        from os import listdir
        features = [f[:-3] for f in listdir('./cogs') if f.endswith('.py') and not f.startswith('_')]
        return features

    async def load_cache(self):
        """Loads server feature configurations into the cache."""
        config_data = await self.bot.data_manager.get_data("server_configs")
        self._config_cache = {
            int(guild_id): set(config.get("disabled_features", []))
            for guild_id, config in config_data.items()
        }
        print("Feature cache loaded.")

    async def is_enabled(self, guild_id: int, feature_name: str) -> bool:
        """Checks if a feature is enabled for a specific guild."""
        if guild_id in self._config_cache:
            return feature_name not in self._config_cache[guild_id]
        return True # Enabled by default

    async def enable_feature(self, guild_id: int, feature_name: str):
        """Enables a feature by removing it from the disabled list."""
        if guild_id in self._config_cache:
            self._config_cache[guild_id].discard(feature_name)
        await self._save_to_storage()

    async def disable_feature(self, guild_id: int, feature_name: str):
        """Disables a feature by adding it to the disabled list."""
        if guild_id not in self._config_cache:
            self._config_cache[guild_id] = set()
        self._config_cache[guild_id].add(feature_name)
        await self._save_to_storage()

    async def _save_to_storage(self):
        """Saves the feature config cache back to the JSON file."""
        storable_data = {
            str(gid): {"disabled_features": list(disabled)}
            for gid, disabled in self._config_cache.items() if disabled
        }
        await self.bot.data_manager.save_data("server_configs", storable_data)