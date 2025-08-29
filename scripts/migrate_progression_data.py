# --- scripts/migrate_progression_data.py ---

import json
from pathlib import Path
import os

"""
A one-time script to migrate old leveling, profiles, and card settings
into the new unified `progression.json` format for the PEAK architecture.

HOW TO USE:
1. Make sure your old bot is offline.
2. Place this script in the bot's root directory (where `main.py` is).
3. Make sure the old data files are in a `/data` directory.
4. Run the script from your terminal: `python scripts/migrate_progression_data.py`
5. It will create a new structure in `data/guilds/`.
6. You can then safely delete the old .json files from the root /data folder.
"""

def load_json(path, default={}):
    if not path.exists():
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def migrate():
    print("--- Starting Data Migration for Progression Plugin ---")
    
    # Define paths
    old_data_path = Path("data")
    new_data_path = old_data_path / "guilds"
    
    old_levels_file = old_data_path / "leveling_data.json"
    old_profiles_file = old_data_path / "profiles.json"
    old_cards_file = old_data_path / "rank_card_settings.json"

    # Load old data
    levels_data = load_json(old_levels_file)
    profiles_data = load_json(old_profiles_file)
    cards_data = load_json(old_cards_file)

    all_guilds = set(levels_data.keys()) | set(profiles_data.keys()) | set(cards_data.keys())
    
    if not all_guilds:
        print("No guild data found to migrate.")
        return

    migrated_guilds = 0
    migrated_users = 0

    for guild_id in all_guilds:
        print(f"Processing Guild ID: {guild_id}...")
        new_guild_progression_data = {"users": {}}
        
        guild_levels = levels_data.get(guild_id, {})
        guild_profiles = profiles_data.get(guild_id, {})
        guild_cards = cards_data.get(guild_id, {})

        all_users = set(guild_levels.keys()) | set(guild_profiles.keys()) | set(guild_cards.keys())

        for user_id in all_users:
            new_user_data = {}
            
            # Migrate leveling
            if user_id in guild_levels:
                new_user_data['xp'] = guild_levels[user_id].get('xp', 0)
            
            # Migrate profiles
            if user_id in guild_profiles:
                new_user_data['profile'] = guild_profiles[user_id]
            
            # Migrate card settings
            if user_id in guild_cards:
                new_user_data['card'] = guild_cards[user_id]
            
            new_guild_progression_data["users"][user_id] = new_user_data
            migrated_users += 1

        # Save the new unified file
        new_file_path = new_data_path / guild_id / "progression.json"
        save_json(new_file_path, new_guild_progression_data)
        migrated_guilds += 1
        print(f"  > Saved data for {len(all_users)} users to {new_file_path}")

    print("\n--- Migration Complete ---")
    print(f"Migrated data for {migrated_users} users across {migrated_guilds} guilds.")
    print("You can now safely delete leveling_data.json, profiles.json, and rank_card_settings.json")

if __name__ == "__main__":
    migrate()