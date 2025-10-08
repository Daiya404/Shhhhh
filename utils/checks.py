# utils/checks.py
import discord

async def is_bot_admin(ctx: discord.ApplicationContext) -> bool:
    """
    A reusable, central check to see if a user is a bot admin.
    This can be imported and used by any cog.
    """
    # Server administrators are always bot admins.
    if ctx.author.guild_permissions.administrator:
        return True

    # Check our saved list of admins.
    bot_admins_data = await ctx.bot.data_manager.get_data("bot_admins")
    guild_admins = bot_admins_data.get(str(ctx.guild.id), [])

    return ctx.author.id in guild_admins