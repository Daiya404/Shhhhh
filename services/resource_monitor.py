# services/resource_monitor.py
import psutil
import os

class ResourceMonitor:
    def __init__(self):
        # Get the current process the bot is running in.
        self.process = psutil.Process(os.getpid())

    def get_memory_usage_mb(self) -> float:
        """
        Returns the bot's current RAM usage (Resident Set Size) in megabytes.
        """
        memory_bytes = self.process.memory_info().rss
        # The conversion from bytes to megabytes is bytes / (1024 * 1024)
        return memory_bytes / 1048576