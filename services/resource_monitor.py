# services/resource_monitor.py
import psutil
import os

class ResourceMonitor:
    def __init__(self):
        """Initializes the monitor and establishes a baseline for CPU usage."""
        self.process = psutil.Process(os.getpid())
        # The first call to cpu_percent returns 0.0 or None, this initializes it.
        self.process.cpu_percent(interval=None)

    def get_memory_usage_mb(self) -> float:
        """Returns the bot's current RAM usage (RSS) in megabytes."""
        memory_bytes = self.process.memory_info().rss
        return memory_bytes / (1024 * 1024)

    def get_cpu_usage_percent(self) -> float:
        """
        Returns the bot's current CPU usage as a percentage.
        This is non-blocking and reflects usage since the last call.
        """
        return self.process.cpu_percent(interval=None)

    def get_thread_count(self) -> int:
        """Returns the total number of threads the bot process is using."""
        return self.process.num_threads()