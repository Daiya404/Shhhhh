import time
from collections import defaultdict, deque
from typing import Deque, Tuple

class FrustrationManager:
    def __init__(self, bot):
        self.bot = bot
        
        # --- Tunable Parameters ---
        # How many commands a user can use in TIME_WINDOW before being considered 'annoyed'.
        self.ANNOYED_THRESHOLD = 3
        # How many commands before being considered 'frustrated'.
        self.FRUSTRATED_THRESHOLD = 5
        # The time window in seconds to check for spam.
        self.TIME_WINDOW = 10 
        # The maximum number of command timestamps to store per user.
        self.HISTORY_LENGTH = 15

        # Data structure to hold user command history.
        # { user_id: deque([timestamp1, timestamp2, ...]) }
        self.user_history: defaultdict[int, Deque[float]] = defaultdict(
            lambda: deque(maxlen=self.HISTORY_LENGTH)
        )

    def record_command_usage(self, user_id: int):
        """Records that a user has used a command at the current time."""
        self.user_history[user_id].append(time.time())

    def get_frustration_level(self, user_id: int) -> int:
        """
        Calculates a frustration level based on recent command usage.
        
        Returns:
            0: Calm
            1: Annoyed (e.g., 3+ commands in 10s)
            2: Frustrated (e.g., 5+ commands in 10s)
        """
        history = self.user_history.get(user_id)
        if not history:
            return 0  # Calm

        now = time.time()
        
        # Count commands issued within the defined time window.
        recent_command_count = sum(1 for ts in history if now - ts <= self.TIME_WINDOW)
        
        if recent_command_count >= self.FRUSTRATED_THRESHOLD:
            return 2  # Frustrated
        if recent_command_count >= self.ANNOYED_THRESHOLD:
            return 1  # Annoyed
        
        return 0  # Calm