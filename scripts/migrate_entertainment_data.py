# --- scripts/migrate_entertainment_data.py ---

import json
from pathlib import Path

def load_json(path, default={}):
    if not path.exists(): return default
    with open(path, 'r', encoding='utf-8') as f: return json.load(f)

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)

def migrate():
    print("--- Starting Data Migration for Entertainment Plugins ---")
    old_data_path = Path("data")
    new_data_path = old_data_path / "guilds"

    # --- Migrate Fun Embeds for QuickGamesPlugin ---
    old_embeds_file = old_data_path / "fun_embeds.json"
    embeds_data = load_json(old_embeds_file)

    if not embeds_data:
        print("No fun_embeds.json found to migrate.")
    else:
        for guild_id, data in embeds_data.items():
            new_guild_data = {"embed_urls": data}
            new_file_path = new_data_path / guild_id / "quick_games.json"
            save_json(new_file_path, new_guild_data)
            print(f"Migrated embed data for Guild {guild_id} to {new_file_path}")

    print("\n--- Migration Complete ---")
    print("You can now safely delete fun_embeds.json.")

if __name__ == "__main__":
    migrate()