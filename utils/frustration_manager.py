import time
from discord.ext import commands
from discord import Interaction

# The time window in seconds for tracking repeated commands.
FRUSTRATION_WINDOW = 120

def get_frustration_level(bot: commands.Bot, interaction: Interaction) -> int:
    """
    Checks and updates the user's command usage to determine a "frustration level".

    This function is the core of making the bot feel more human. It keeps a
    short-term memory of command usage per user.

    Returns:
        An integer representing the number of times the user has used the
        same command recently (0 for the first time, 1 for the second, etc.).
    """
    user_id = interaction.user.id
    # We use interaction.command.qualified_name to correctly handle subcommands like "/botadmin add"
    command_name = interaction.command.qualified_name

    now = time.time()

    # Access the bot's central command usage tracker
    timestamps = bot.command_usage[user_id][command_name]

    # 1. Clean out old timestamps that are outside our frustration window
    recent_timestamps = [ts for ts in timestamps if now - ts < FRUSTRATION_WINDOW]

    # 2. Add the current command's timestamp
    recent_timestamps.append(now)

    # 3. Update the tracker with the new list of recent uses
    bot.command_usage[user_id][command_name] = recent_timestamps

    # 4. The frustration level is how many times they've done this recently (minus one)
    return len(recent_timestamps) - 1