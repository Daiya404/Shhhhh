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
    },
    "word_blocker": {
        "word_added": "Noted. I will now watch for that word.",
        "word_removed": "Fine, I've removed that word from the blocklist.",
        "already_blocked": "I'm already blocking that word. Pay attention.",
        "not_blocked": "I wasn't blocking that word to begin with.",
        "list_empty": "There are no words on the global blocklist.",
        "user_list_empty": "No specific words are blocked for **{user}**.",
        "channel_warning": "{user}, your message contained a blocked term and was deleted. Watch it."
    },
    "link_fixer": {
        "personal_opt_out": "Alright, I'll leave your links alone from now on. Your personal link fixing is **OFF**.",
        "personal_opt_in": "Hmph. So you need my help after all? Fine, I'll fix your links again. Your personal link fixing is **ON**."
    },
    "clear": {
        "clear_success": "Done. I've deleted `{count}` messages. The channel looks much cleaner now.",
        "clear_user_success": "Alright, I got rid of `{count}` of {user}'s messages. Happy now?",
        "eat_start_set": "Start point set. Now reply to the end message with `!tika end`.",
        "eat_success": "Done. I ate `{count}` messages between the two points. Hope they were tasty.",
        "end_no_start": "I can't end what hasn't been started. Use `!tika eat` by replying to a message first.",
        "must_reply": "You have to reply to a message for that to work. Obviously.",
        "error_forbidden": "I can't do that. I'm missing the 'Manage Messages' permission.",
        "error_general": "Something went wrong. The messages might be too old, or Discord is just having a moment.",
        "error_not_found": "Couldn't find one of the messages you replied to. Starting over.",
        "search_started": "Searching for messages containing: `{target}`. This might take a moment...",
        "search_completed": "Found and deleted `{count}` messages containing: `{target}`",
        "search_no_matches": "No messages found containing: `{target}`. Nothing to delete.",
        "search_cancelled": "Search and delete operation cancelled.",
        "search_timeout": "Confirmation timed out. Operation cancelled.",
        "invalid_regex": "Invalid regex pattern: {error}"
    },
    "reminders": {
        "reminder_set": "Fine, I'll remember that for you. It's not like I have anything better to do. Your reminder ID is `{id}`.",
        "reminder_dm_title": "Hey. You told me to remind you about this.",
        "reminder_channel_ping": "{user}, I tried to DM you, but you've got them blocked. You told me to remind you about this.",
        "reminder_channel_title": "A reminder for {user}!",
        "list_empty": "You have no active reminders.",
        "list_title": "Your Active Reminders", 
        "deleted": "Okay, I've forgotten about that reminder.",  
        "admin_deleted": "Done. I have deleted that reminder.",
        "delete_not_found": "I can't find a reminder with that ID. Are you sure you typed it correctly?", 
        "delete_not_yours": "That's not your reminder to delete. Mind your own business.", 
        "invalid_time": "That doesn't look like a real time format. Use something like `1d`, `2h30m`, `tomorrow`, or `1 week`.",
        "delivery_dm": "Okay, I'll send your reminders and timers via **Direct Message** from now on.",
        "delivery_channel": "Got it. I'll send your reminders and timers publicly in the **Original Channel** from now on."
    },
    "custom_roles": {
        "set_responses": [
            "There, your role is set. Don't mess it up.",
            "Changed it again? Fine. It's updated.",
            "Are you sure about this one? Whatever, it's done.",
            "Okay, this is the last time I'm changing it for a bit. Your role is updated. Now stop."
        ],
        "role_view": "You want to admire the role I made for you? Here are the details.",
        "role_deleted": "Done. Your custom role has been deleted.",
        "no_role": "You don't even have a custom role. Use `/role set` to make one first.",
        "invalid_name": "That's a terrible name for a role. It has invalid characters or is too long. Pick something better.",
        "invalid_color": "That's not a color. Use a real hex code, like `#A020F0`.",
        "target_set": "Understood. I'll now place all new custom roles above the one you specified.",
        "target_too_high": "I can't place roles above that one. It's higher than my own role. Pick something below me.",
        "admin_cleanup": "Cleanup complete. Removed `{count}` orphaned role entries.",
        "admin_no_cleanup": "I checked. There was nothing to clean up. Everything is already perfect, as expected."
    },
    "copy_chapel": {
        "setup_success": "Done. Chapel is now configured. I'll watch for `{emote}` reactions in this server.",
        "invalid_emote": "That doesn't look like a valid custom emote from this server. I'm not adding it.",
        "config_not_found": "Chapel is not configured for this server. An admin needs to set it up first.",
        "config_reset": "Fine, I've completely reset the Chapel configuration for this server."
    },
    "fun_cmds": {
        "coinflip_responses": [
            "Flipping a coin for you. It's **{result}**.",
            "Again? Fine. **{result}** this time.",
            "Are we going to do this all day? It's **{result}**.",
            "This is the last time. **{result}**. Now go do something productive."
        ],
        "rps_win": "You chose **{user_choice}** and I chose **{bot_choice}**. Hmph. You win this time.",
        "rps_lose": "You chose **{user_choice}** and I chose **{bot_choice}**. Predictable. I win.",
        "rps_tie": "We both chose **{user_choice}**. How boring.",
        "embed_added": "Fine, I've added that image to the `{command}` list for this server. I hope it's a good one.",
        "embed_invalid_url": "That doesn't look like a real URL. Try again.",
        "error_roll_format": "That's not how you roll dice. Use the format `1d6` or `2d20`.",
        "no_gif_sources": "No GIF sources available for that command.",
        "gif_source_set": "Fine, I'll use GIFs from **{guild_name}** for your `{command}` commands from now on.",
        "invalid_gif_source": "I can't use that source. Either I'm not in that server or it has no GIFs for that command.",
        "gif_source_reset": "Hmph. Back to the default GIFs for `{command}` it is."
    },
    "server_games": {
        "challenge_sent": "Hmph. {challenger} has challenged {opponent} to a game of **{game_name}**. Are you going to accept, {opponent}, or are you scared?",
        "challenge_accepted": "Fine, the game is on. It's **{player}'s** turn to move.",
        "challenge_declined": "Looks like {opponent} was too scared to play. How predictable.",
        "challenge_timeout": "Well, {opponent} didn't respond. I guess we have our answer.",
        "game_already_running": "You're already in a game. Finish it before you start another one.",
        "opponent_in_game": "They're already busy with another game. Find someone else to bother.",
        "not_your_turn": "It's not your turn. Don't be so impatient.",
        "invalid_move": "You can't play there. Are you even paying attention to the board?",
        "win_message": "The game is over. **{winner}** won. I guess that makes you the loser, {loser}.",
        "draw_message": "A draw. How utterly boring. Neither of you could win.",
        "game_timeout": "The game timed out because someone took too long. Pathetic.",
        "game_resigned": "**{player}** resigned from the game. How disappointing. **{winner}** wins by default.",
        "hangman_start": "Alright, I've thought of a word. Start guessing letters. You have {lives} wrong guesses before you lose.",
        "hangman_win": "You actually guessed it. The word was **{word}**. I'm impressed... for once.",
        "hangman_lose": "You lose. How disappointing. The word was **{word}**.",
        "hangman_already_guessed": "You already guessed that letter. Try to keep up.",
        "hangman_invalid": "That's not a valid letter. Try again.",
        "not_in_game": "You're not in any game to resign from.",
        "dm_opponent_required": "In DMs, you need to mention the opponent you want to challenge.",
        "self_challenge": "You can't challenge yourself. Don't be ridiculous.",
        "bot_challenge": "You can't challenge a bot. I'd win every time, and it would be boring."
    },
    "word_game": {
        "channel_set": "Okay, the Word Chain game is now locked to {channel}. Try not to make a mess.",
        "already_active": "A game is already active in the designated channel. Don't be impatient.",
        "start_success": "Fine, I've started a new round. The first letter is **{letter}**. Go.",
        "no_scores": "No one has scored any points yet. How utterly predictable.",
        "reset_confirm": "⚠️ **Are you sure?** This will wipe all scores and the entire used word history. This can't be undone.",
        "reset_success": "Done. Everything is gone. I hope you're happy.",
        "reset_cancel": "Reset cancelled. As I thought."
    }
}