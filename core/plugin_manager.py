# --- core/plugin_manager.py ---

import importlib
import inspect
import logging
from pathlib import Path

from plugins.base_plugin import BasePlugin

class PluginManager:
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("PluginManager")
        self.loaded_plugins = {}

    def get_loaded_plugins(self):
        """Returns a list of loaded plugin instances, sorted by priority."""
        # Sorting based on config load_order
        order = self.bot.config.get('plugins', {}).get('load_order', {})
        return sorted(
            self.loaded_plugins.values(),
            key=lambda p: order.get(p.name, 99) # Default to low priority
        )

    async def load_plugins(self):
        """Discover and load all valid plugins from the /plugins directory."""
        plugins_dir = Path("plugins")
        self.logger.info("--- Discovering and loading plugins... ---")
        
        for module_path in plugins_dir.rglob("*.py"):
            if module_path.name.startswith(("_", "base_")):
                continue

            module_name = str(module_path.relative_to('.').with_suffix('')).replace('/', '.').replace('\\', '.')
            
            try:
                module = importlib.import_module(module_name)
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                        plugin_instance = obj(self.bot)
                        
                        # Use the plugin's self-declared name as the key
                        plugin_key = plugin_instance.name
                        if plugin_key in self.loaded_plugins:
                            self.logger.warning(f"Duplicate plugin name '{plugin_key}' found. Skipping.")
                            continue

                        await self.bot.add_cog(plugin_instance)
                        self.loaded_plugins[plugin_key] = plugin_instance
                        self.logger.info(f"✅ Loaded Plugin: {plugin_key} ({module_path.name})")
                        break # Assume one plugin class per file
            
            except Exception as e:
                self.logger.error(f"❌ Failed to load plugin from {module_path.name}", exc_info=e)

        self.logger.info(f"--- Loaded {len(self.loaded_plugins)} plugin(s) successfully. ---")