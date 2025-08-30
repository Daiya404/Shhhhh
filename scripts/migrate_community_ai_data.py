# --- scripts/migrate_community_ai_data.py ---

import json
from pathlib import Path

def load_json(path, default={}):
    if not path.exists(): return default
    with open(path, 'r', encoding='utf-8') as f: return json.load(f)

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)

def migrate():
    print("--- Starting Data Migration for Community & AI Plugins ---")
    old_data_path = Path("data")
    new_data_path = old_data_path / "guilds"

    # --- Migrate Chapel Data ---
    role_settings = load_json(old_data_path / "role_settings.json")
    message_map = load_json(old_data_path / "chapel_message_map.json")
    for guild_id, settings in role_settings.items():
        if "chapel_config" in settings:
            chapel_config = settings["chapel_config"]
            new_data = {
                "settings": {
                    "enabled": True,
                    "channel_id": chapel_config.get("channel_id"),
                    "emote": chapel_config.get("emote"),
                    "threshold": chapel_config.get("threshold", 3)
                },
                "message_map": message_map.get(guild_id, {})
            }
            save_json(new_data_path / guild_id / "chapel.json", new_data)
            print(f"Migrated Chapel data for Guild {guild_id}")

    # --- Migrate AI Chatbot Config ---
    chatbot_config = load_json(old_data_path / "chatbot_config.json")
    if chatbot_config and "character" in chatbot_config:
        # We'll apply this config to all guilds that had chapel data, as a guess.
        for guild_id in role_settings.keys():
            new_data = {"character": chatbot_config["character"]}
            save_json(new_data_path / guild_id / "ai_chat.json", new_data)
            print(f"Migrated global AI config for Guild {guild_id}")

    print("\n--- Migration Complete ---")

if __name__ == "__main__":
    migrate()