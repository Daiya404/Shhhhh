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
    "detention": {
        "channel_set": "Understood. From now on, all detention sentences will be served in {channel}.",
        "no_channel_set": "An admin needs to set a detention channel first using `/detention set-channel`.",
        "detention_start": "Done. {user} has been placed in detention. I've created instructions for them in {channel}.",
        "milestone_progress": "You're making progress, {user}. Only `{remaining}` more to go.",
        "detention_done": "Hmph. You finished. I've restored your roles. Try to be less of a problem from now on.",
        "detention_released": "Fine, I've released {user} from detention. I hope you know what you're doing.",
        "missing_role": "I can't do my job if you haven't done yours. A role named `BEHAVE` needs to exist first.",
        "cant_manage_user": "I can't manage `{user}`. Their role is higher than mine. That's a 'you' problem, not a 'me' problem.",
        "cant_manage_role": "The `BEHAVE` role is above my top role. I can't assign it to anyone. Move it down.",
        "already_detained": "That user is already in detention. Don't waste my time.",
        "not_detained": "That user isn't in detention. I can't release someone who is already free.",
        "no_one_detained": "No one is in detention. The server is behaving... for now.",
        "self_detention": "Don't be ridiculous. I'm not putting you in detention.",
        "bot_detention": "You can't put a bot in detention. It wouldn't learn anything.",
        "channel_perms_missing": "I can't work in that channel. I need permissions to Send Messages, Manage Messages (for pinning), and Add Reactions."
    },
    "auto_reply": {
        "trigger_set": "Fine. If anyone says `{trigger}`, I'll reply with that. I hope it's not something stupid.",
        "alt_added": "Another one? Okay, I've added `{alternative}` as an alternative for `{trigger}`.",
        "trigger_removed": "Noted. I'll no longer reply to `{trigger}`.",
        "trigger_not_found": "I can't find a trigger with that name. Try checking the list.",
        "already_exists": "That trigger or alternative already exists. Pay attention.",
        "list_empty": "There are no auto-replies set up for this server.",
        "error_empty": "You can't set an empty trigger or alternative. Obviously."
    }
}