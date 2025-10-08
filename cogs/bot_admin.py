# cogs/bot_admin.py
import discord
from discord.ext import commands
from discord import option

# --- Decorator ---
def is_bot_admin():
    """
    A custom check to see if the user is a bot admin.
    Server administrators are always considered bot admins.
    """
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        # Guild owners and users with Administrator permission are always bot admins.
        if ctx.author.guild_permissions.administrator:
            return True

        # Check the manually added list from our data file.
        bot_admins_data = await ctx.bot.data_manager.get_data("bot_admins")
        guild_admins = bot_admins_data.get(str(ctx.guild.id), [])

        return ctx.author.id in guild_admins
    return commands.check(predicate)

# --- Cog ---
class BotAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Create a slash command group for better organization
    admin_group = discord.SlashCommandGroup(
        "bot-admin",
        "Commands to manage who can use Tika's admin commands.",
        checks=[is_bot_admin()] # Apply the check to the entire group
    )

    @admin_group.command(name="add", description="Adds a user as a bot admin.")
    @option("user", discord.Member, description="The user to grant admin permissions to.")
    async def add(self, ctx: discord.ApplicationContext, user: discord.Member):
        bot_admins_data = await self.bot.data_manager.get_data("bot_admins")
        guild_id_str = str(ctx.guild.id)

        # Initialize list if guild is not in the data yet
        if guild_id_str not in bot_admins_data:
            bot_admins_data[guild_id_str] = []

        if user.id in bot_admins_data[guild_id_str]:
            return await ctx.respond(f"{user.display_name} is already a bot admin.", ephemeral=True)

        bot_admins_data[guild_id_str].append(user.id)
        await self.bot.data_manager.save_data("bot_admins", bot_admins_data)
        await ctx.respond(f"Done. I will now recognize {user.mention} as a bot admin.")

    @admin_group.command(name="remove", description="Removes a user as a bot admin.")
    @option("user", discord.Member, description="The user to remove admin permissions from.")
    async def remove(self, ctx: discord.ApplicationContext, user: discord.Member):
        bot_admins_data = await self.bot.data_manager.get_data("bot_admins")
        guild_admins = bot_admins_data.get(str(ctx.guild.id), [])

        if user.id not in guild_admins:
            return await ctx.respond(f"{user.display_name} wasn't a bot admin to begin with.", ephemeral=True)

        guild_admins.remove(user.id)
        await self.bot.data_manager.save_data("bot_admins", bot_admins_data)
        await ctx.respond(f"Noted. {user.mention} is no longer a bot admin.")

    @admin_group.command(name="list", description="Lists all current bot admins.")
    async def list_admins(self, ctx: discord.ApplicationContext):
        bot_admins_data = await self.bot.data_manager.get_data("bot_admins")
        guild_admins = bot_admins_data.get(str(ctx.guild.id), [])

        if not guild_admins:
            return await ctx.respond("No delegated bot admins have been added. Only server admins can use my commands.", ephemeral=True)

        description = "\n".join(f"- <@{user_id}>" for user_id in guild_admins)
        embed = discord.Embed(
            title="Delegated Bot Admins",
            description=description,
            color=discord.Color.blurple()
        )
        await ctx.respond(embed=embed, ephemeral=True)

def setup(bot):
    bot.add_cog(BotAdmin(bot))