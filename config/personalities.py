# config/personalities.py
"""
Central repository for all of Tika's text-based personality traits.
This includes console messages, command responses, and more.
"""
import random

# Tika's voice for the console and log files.
# This makes it feel like she is the one running the program.
CONSOLE_MESSAGES = {
    "startup": {
        "booting": "Booting up. Don't rush me.",
        "token_fail": "No token, no work. Create a 'token.txt' in the 'secrets' folder. I'm not doing anything until you do.",
        "login_fail": "Invalid token. Did you copy it correctly? I can't log in with this.",
        "unexpected_fail": "Something broke during startup. You should probably look at the logs. It's not my fault.",
    },
    "cogs": {
        "loading": "Loading cogs... Let's see what features I have to work with today.",
        "load_success": "Successfully loaded the {cog_name} cog.",
        "load_fail": "Hmph. I couldn't load the {cog_name} cog. Error: {error}",
        "all_loaded": "Finished loading {count} cogs. I suppose I'm ready now.",
    },
    "shutdown": {
        "request": "Shutdown requested. Fine, I'll go."
    },
    "on_ready": {
        "login": "Logged in as: {username} (ID: {user_id})",
        "servers": "Observing {count} server(s).",
        "ready": [
            "Online and ready. I suppose.",
            "I'm here. What do you need?",
            "Tika is online. Try not to break anything.",
        ]
    }
}


def get_console_message(key_path: str, **kwargs) -> str:
    """
    Safely retrieves a formatted console message.
    Example: get_console_message("on_ready.ready")
    """
    try:
        keys = key_path.split('.')
        message_pool = CONSOLE_MESSAGES
        for key in keys:
            message_pool = message_pool[key]

        # If the result is a list, pick a random one.
        if isinstance(message_pool, list):
            message = random.choice(message_pool)
        else:
            message = message_pool

        return message.format(**kwargs)
    except (KeyError, TypeError) as e:
        # Fallback for invalid keys
        print(f"[Personality Engine Error] Could not find message for key: {key_path}. Error: {e}")
        return "An internal message is missing."