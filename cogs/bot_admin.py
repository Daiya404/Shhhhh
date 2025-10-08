# cogs/bot_admin.py
import discord
from discord.ext import commands
from discord import option
from utils.checks import is_bot_admin # Import our central check

class BotAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- COMMAND 1: /bot-admin (Admin Only) ---
    # The command name the user sees is "bot-admin".
    @commands.slash_command(name="bot-admin", description="Add or remove a bot admin.")
    @commands.check(is_bot_admin)
    @option("action", description="The action to perform.", choices=["Add", "Remove"])
    @option("user", discord.Member, description="The user to manage.")
    # RENAMED: The internal function name no longer starts with 'bot_'.
    async def manage_admins(self, ctx: discord.ApplicationContext, action: str, user: discord.Member):
        
        if action == "Add":
            bot_admins_data = await self.bot.data_manager.get_data("bot_admins")
            guild_id_str = str(ctx.guild.id)

            if guild_id_str not in bot_admins_data:
                bot_admins_data[guild_id_str] = []

            if user.id in bot_admins_data[guild_id_str]:
                await ctx.respond(f"{user.display_name} is already a bot admin.", ephemeral=True)
                return

            bot_admins_data[guild_id_str].append(user.id)
            await self.bot.data_manager.save_data("bot_admins", bot_admins_data)
            await ctx.respond(f"Done. I will now recognize {user.mention} as a bot admin.", ephemeral=True)

        elif action == "Remove":
            bot_admins_data = await self.bot.data_manager.get_data("bot_admins")
            guild_admins = bot_admins_data.get(str(ctx.guild.id), [])

            if user.id not in guild_admins:
                await ctx.respond(f"{user.display_name} wasn't a bot admin to begin with.", ephemeral=True)
                return

            guild_admins.remove(user.id)
            await self.bot.data_manager.save_data("bot_admins", bot_admins_data)
            await ctx.respond(f"Noted. {user.mention} is no longer a bot admin.", ephemeral=True)

    # --- COMMAND 2: /bot-admin-list (Public) ---
    # The command name the user sees is "bot-admin-list".
    @commands.slash_command(name="bot-admin-list", description="Lists all current bot admins.")
    # RENAMED: The internal function name no longer starts with 'bot_'.
    async def list_admins(self, ctx: discord.ApplicationContext):
        bot_admins_data = await self.bot.data_manager.get_data("bot_admins")
        guild_admins = bot_admins_data.get(str(ctx.guild.id), [])

        if not guild_admins:
            await ctx.respond("No delegated bot admins have been added. Only server admins can use my commands.", ephemeral=True)
            return

        description = "\n".join(f"- <@{user_id}>" for user_id in guild_admins)
        embed = discord.Embed(
            title="Delegated Bot Admins",
            description=description,
            color=discord.Color.blurple()
        )
        await ctx.respond(embed=embed, ephemeral=True)
        
    # --- Error Handler ---
    async def cog_command_error(self, ctx: discord.ApplicationContext, error: discord.DiscordException):
        if isinstance(error, commands.CheckFailure):
            await ctx.respond("You don't have permission to do that.", ephemeral=True)
        else:
            print(f"An unhandled error occurred in BotAdmin cog: {error}")
            await ctx.respond("Something went wrong on my end.", ephemeral=True)

def setup(bot):
    bot.add_cog(BotAdmin(bot))