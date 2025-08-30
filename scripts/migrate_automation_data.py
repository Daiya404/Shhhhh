# --- scripts/migrate_automation_data.py ---
# (Only the migrate function needs to be replaced)

from anyio import Path
from scripts.migrate_entertainment_data import load_json, save_json


def migrate():
    print("--- Starting Data Migration for Automation & Game Plugins ---")
    old_data_path = Path("data")
    new_data_path = old_data_path / "guilds"

    # --- Migrate Word Game ---
    word_game_scores = load_json(old_data_path / "word_game_scores.json")
    word_game_state = load_json(old_data_path / "word_game_state.json")
    for guild_id in set(word_game_scores.keys()) | set(word_game_state.keys()):
        new_data = {
            "scores": word_game_scores.get(guild_id, {}),
            "game_state": word_game_state.get(guild_id)
        }
        save_json(new_data_path / guild_id / "word_game.json", new_data)
        print(f"Migrated Word Game data for Guild {guild_id}")

    # --- Migrate Message Automation (Auto-Reply & Link Fixer) ---
    auto_replies = load_json(old_data_path / "auto_replies.json")
    link_fixer_settings = load_json(old_data_path / "link_fixer_settings.json")
    all_guilds = set(auto_replies.keys()) | set(link_fixer_settings.keys())

    for guild_id in all_guilds:
        # Convert auto-reply format
        replies_dict = {
            trigger: data.get("reply")
            for trigger, data in auto_replies.get(guild_id, {}).items()
            if data.get("reply")
        }

        # --- THIS IS THE CORRECTED LOGIC ---
        old_fixer_config = link_fixer_settings.get(guild_id, {})
        new_fixer_config = {
            # Correctly map 'global_enabled' to 'enabled', defaulting to True if not present
            "enabled": old_fixer_config.get("global_enabled", True),
            "opt_out": old_fixer_config.get("user_opt_out", [])
        }
        # --- END OF CORRECTION ---

        new_data = {
            "auto_replies": replies_dict,
            "link_fixer": new_fixer_config
        }
        save_json(new_data_path / guild_id / "message_automation.json", new_data)
        print(f"Migrated Message Automation data for Guild {guild_id}")
    
    # --- Migrate Reminders ---
    reminders = load_json(old_data_path / "reminders.json", default=[])
    if reminders:
        new_reminders_data = {"items": reminders}
        # Using a global data file instead of guild-specific for reminders
        save_json(old_data_path / "global_reminders.json", new_reminders_data)
        print(f"Migrated {len(reminders)} reminders to global file.")

    print("\n--- Migration Complete ---")

if __name__ == "__main__":
    migrate()