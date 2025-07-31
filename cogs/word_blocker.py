import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime, timedelta, timezone

# Import the custom admin check from our other cog
from .bot_admin import BotAdmin

# --- Personality Responses for this Cog ---
PERSONALITY = {
    "clear_success": "Done. I've deleted `{count}` messages. The channel looks much cleaner now.",
    "clear_user_success": "Alright, I got rid of `{count}` of {user}'s messages. Happy now?",
    "nuke_start_set": "Start point set. Now reply to the end message with `!tika nuke end`.",
    "nuke_success": "Annihilation complete. I've erased `{count}` messages from existence.",
    "nuke_no_start": "I can't end what hasn't begun. Use `!tika nuke start` by replying to a message first.",
    "must_reply": "You have to reply to a message for that to work. Obviously.",
    "error_forbidden": "I can't do that. I'm missing the 'Manage Messages' permission.",
    "error_general": "Something went wrong. The messages might have been too old, or Discord is just having a moment.",
    "error_not_found": "Couldn't find one of the messages you replied to. Starting over."
}

class Clear(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {channel_id: start_message_id}
        self.nuke_start_points: dict[int, int] = {}

    async def cog_check(self, ctx: commands.Context) -> bool:
        """A universal check for all prefix commands in this cog."""
        if not ctx.guild: return False # Not in a server
        
        # Manually perform the bot admin check for prefix commands
        cog = self.bot.get_cog('BotAdmin')
        if not (ctx.author.guild_permissions.administrator or (cog and str(ctx.guild.id) in cog.bot_admins and ctx.author.id in cog.bot_admins[str(ctx.guild.id)])):
            return False # Silently fail if they don't have perms
        return True

    # --- Standard Slash Command ---
    @app_commands.command(name="clear", description="Deletes a specified number of recent messages.")
    @app_commands.describe(
        amount="The number of messages to delete (1-100).",
        user="Optional: Filter to only delete messages from this user."
    )
    @BotAdmin.is_bot_admin()
    async def slash_clear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], user: discord.Member = None):
        await interaction.response.defer(ephemeral=True)

        def check(message):
            return user is None or message.author == user

        try:
            deleted_messages = await interaction.channel.purge(limit=amount, check=check, bulk=True)
            if user:
                response = PERSONALITY["clear_user_success"].format(count=len(deleted_messages), user=user.mention)
            else:
                response = PERSONALITY["clear_success"].format(count=len(deleted_messages))
            await interaction.followup.send(response, ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(PERSONALITY["error_forbidden"], ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send(PERSONALITY["error_general"], ephemeral=True)


    # --- Unique Prefix "Nuke" Command Group ---
    @commands.group(invoke_without_command=True)
    async def nuke(self, ctx: commands.Context):
        """Base command for the two-step message nuke feature."""
        await ctx.send("To clear a range of messages, reply to the first message with `!tika nuke start`, then reply to the last with `!tika nuke end`.", delete_after=15)
        try:
            await ctx.message.delete(delay=15)
        except discord.NotFound: pass

    @nuke.command(name="start")
    async def nuke_start(self, ctx: commands.Context):
        """Sets the starting message for the nuke."""
        if not ctx.message.reference:
            await ctx.send(PERSONALITY["must_reply"], delete_after=10)
        else:
            self.nuke_start_points[ctx.channel.id] = ctx.message.reference.message_id
            await ctx.send(PERSONALITY["nuke_start_set"], delete_after=10)
        await ctx.message.delete()

    @nuke.command(name="end")
    async def nuke_end(self, ctx: commands.Context):
        """Sets the end message and executes the nuke."""
        if not ctx.message.reference:
            await ctx.send(PERSONALITY["must_reply"], delete_after=10)
            return await ctx.message.delete()

        if ctx.channel.id not in self.nuke_start_points:
            await ctx.send(PERSONALITY["nuke_no_start"], delete_after=10)
            return await ctx.message.delete()

        start_id = self.nuke_start_points.pop(ctx.channel.id)
        end_id = ctx.message.reference.message_id
        await ctx.message.delete() # Delete the user's `!tika nuke end` command immediately

        try:
            start_msg = await ctx.channel.fetch_message(start_id)
            end_msg = await ctx.channel.fetch_message(end_id)
        except discord.NotFound:
            return await ctx.send(PERSONALITY["error_not_found"], delete_after=10)

        # Ensure chronological order
        if start_msg.created_at > end_msg.created_at:
            start_msg, end_msg = end_msg, start_msg

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=13, hours=23) # A safe buffer

        # Collect all messages between the two points
        history = [msg async for msg in ctx.channel.history(limit=None, after=start_msg, before=end_msg)]
        to_delete = [msg for msg in history if msg.created_at > cutoff_date]
        
        # Add the boundary messages if they are also recent enough
        if start_msg.created_at > cutoff_date: to_delete.append(start_msg)
        if end_msg.created_at > cutoff_date: to_delete.append(end_msg)
        
        if not to_delete:
            return await ctx.send("No recent messages found in that range to delete.", delete_after=10)

        try:
            await ctx.channel.delete_messages(to_delete)
            await ctx.send(PERSONALITY["nuke_success"].format(count=len(to_delete)), delete_after=10)
        except discord.Forbidden:
            await ctx.send(PERSONALITY["error_forbidden"], delete_after=10)
        except discord.HTTPException:
            await ctx.send(PERSONALITY["error_general"], delete_after=10)

async def setup(bot):
    await bot.add_cog(Clear(bot))