# utils/frustration_manager.py
import time
from discord import Interaction
from discord.ext import commands

# The time window in seconds for tracking repeated commands.
FRUSTRATION_WINDOW = 120

def get_frustration_level(bot: commands.Bot, interaction: Interaction) -> int:
    """
    Checks and updates the user's command usage to determine a "frustration level".
    This function accesses the bot's central command_usage dictionary.
    """
    user_id = interaction.user.id
    # We use interaction.command.qualified_name to correctly handle subcommands
    command_name = interaction.command.qualified_name if interaction.command else "unknown"

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