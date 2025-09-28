"""
This file contains all user-facing text strings for the bot.
By centralizing them here, we can easily manage and change the bot's personality.
Each top-level key corresponds to a cog or service.
"""

PERSONALITY_RESPONSES = {
    "general": {
        "permission_denied": "Hmph. You don't have permission to do that.",
    },

    "frustration": {
        "level_1_annoyed": "Don't spam. I heard you the first time.",
        "level_2_frustrated": "If you keep this up, I'm just going to ignore you."
    },

    "bot_admin": {
        "admin_added": "Fine. {user} is now a bot admin.",
        "admin_removed": "As you wish. {user} is no longer a bot admin.",
        "already_admin": "That user is already an admin. Pay attention.",
        "not_admin": "That user isn't an admin, so I can't remove them.",
        "no_admins": "There are no bot admins configured for this server.",
        "admin_list_title": "Bot Admins for this Server"
    },

    "feature_manager": {
        "feature_enabled": "Okay, the `{feature}` feature is now enabled.",
        "feature_disabled": "Hmph. The `{feature}` feature has been disabled.",
        "invalid_feature": "That's not a real feature. Check your spelling.",
        "list_title": "Feature Status",
        "list_enabled": "Enabled",
        "list_disabled": "Disabled"
    },
    
    "backup": {
        "service_not_configured": "The backup service isn't configured. Someone didn't set it up properly.",
        "create_start": "Fine, I'll create a backup now. This might take a moment.",
        "backup_complete": "Backup complete. Your data is safe, I suppose.",
        "backup_failed": "Something went wrong. The backup failed.",
        "no_backups_found": "No backups found. Maybe create one first?",
        "list_title": "Most Recent Backups",
        "clean_start": "Checking for old backups to clean...",
        "clean_complete": "Cleaned up {count} old backup(s).",
        "clean_unnecessary": "No old backups needed cleaning."
    }
}