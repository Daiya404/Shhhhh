# config/personalities.py
PERSONALITY_RESPONSES = {
    "bot_admin": {
        "admin_added": "Fine, I'll acknowledge `{user}`'s commands now. You're taking responsibility for them. 😒",
        "admin_removed": "Noted. `{user}` is no longer a bot admin.",
        "already_admin": "That person is already on the list. Pay attention.",
        "not_admin": "I wasn't listening to that person anyway. Can't remove someone who isn't there.",
        "no_admins": "No extra bot admins have been added. It's just the server administrators.",
        "no_perm_check": "You don't have the required permissions for that command.",
    },
    # You will add more keys here like "detention", "fun_cmds", etc. as you migrate cogs
}