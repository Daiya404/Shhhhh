# cogs/moderation.py
import discord
from discord.ext import commands
import asyncio
from typing import List, Optional
from datetime import datetime, timedelta

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.clear_start_points = {}  # Store start points per channel
        
        # Constants
        self.BULK_DELETE_LIMIT = 100
        self.MESSAGE_AGE_LIMIT = 14  # Days for bulk delete
        self.CONFIRMATION_DELAY = 5  # Seconds

    @commands.command(name="nuke", help="Clears messages. Use '!Tika nuke start' and '!Tika nuke end'.")
    @commands.has_permissions(manage_messages=True)
    async def nuke_messages(self, ctx, action: Optional[str] = None):
        """Clear messages between start and end points or up to a replied message"""
        if action == "start":
            await self._handle_start_point(ctx)
        elif action == "end":
            await self._handle_end_point(ctx)
        else:
            await self._send_temp_message(
                ctx,
                "Don't just stand there! Tell me what to do. `start` or `end`?",
                10
            )

    async def _send_temp_message(self, ctx, content: str, delay: int):
        """Send a temporary message that deletes after specified delay"""
        msg = await ctx.send(content)
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except discord.NotFound:
            pass # Message was already deleted

    async def _handle_start_point(self, ctx):
        """Handle setting the start point for clearing"""
        if not ctx.message.reference or not ctx.message.reference.message_id:
            await ctx.message.delete()
            await self._send_temp_message(ctx, "You have to reply to a message to set a start point, dummy.", 5)
            return

        try:
            start_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            self.clear_start_points[ctx.channel.id] = start_message.id
            
            confirmation_msg = "Alright, I've marked the start point. Now tell me where to end this."
            await ctx.message.delete()
            await self._send_temp_message(ctx, confirmation_msg, self.CONFIRMATION_DELAY)

        except discord.NotFound:
            await ctx.message.delete()
            await self._send_temp_message(ctx, "Are you blind? I can't find that message.", 5)

    async def _handle_end_point(self, ctx):
        """Handle clearing from start point to end point"""
        if ctx.channel.id not in self.clear_start_points:
            await ctx.message.delete()
            await self._send_temp_message(ctx, "Set a start point first with `!Tika nuke start`. I'm not a mind reader.", 5)
            return

        if not ctx.message.reference or not ctx.message.reference.message_id:
            await ctx.message.delete()
            await self._send_temp_message(ctx, "You need to reply to the end message. Honestly.", 5)
            return

        try:
            start_message_id = self.clear_start_points.pop(ctx.channel.id)
            start_message = await ctx.channel.fetch_message(start_message_id)
            end_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            
            await ctx.message.delete()

            # Ensure proper chronological order
            if start_message.created_at > end_message.created_at:
                start_message, end_message = end_message, start_message

            messages_to_delete = await self._collect_messages_between(ctx.channel, start_message, end_message)

            if not messages_to_delete:
                await self._send_temp_message(ctx, "There's nothing to delete between those points.", 5)
                return

            deleted_count = await self._delete_messages_efficiently(ctx.channel, messages_to_delete)
            
            await self._send_temp_message(ctx, f"There. I deleted {deleted_count} messages. Happy now?", self.CONFIRMATION_DELAY)

        except discord.NotFound:
            await self._send_temp_message(ctx, "I couldn't find one of the messages. Try again.", 5)
        except Exception as e:
            await self._send_temp_message(ctx, f"Something went wrong. Ugh. Error: {str(e)}", 5)


    async def _collect_messages_between(self, channel, start_message, end_message):
        messages = [start_message, end_message]
        async for message in channel.history(limit=None, after=start_message, before=end_message):
            messages.append(message)
        return messages

    async def _delete_messages_efficiently(self, channel, messages):
        if not messages:
            return 0
        
        deleted_count = 0
        from datetime import timezone
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=13, hours=23)
        
        recent_messages = [msg for msg in messages if msg.created_at > cutoff_time]
        old_messages = [msg for msg in messages if msg.created_at <= cutoff_time]

        for i in range(0, len(recent_messages), self.BULK_DELETE_LIMIT):
            chunk = recent_messages[i:i + self.BULK_DELETE_LIMIT]
            if len(chunk) > 1:
                await channel.delete_messages(chunk)
                deleted_count += len(chunk)
            elif len(chunk) == 1:
                await chunk[0].delete()
                deleted_count += 1
            await asyncio.sleep(1) # a little delay to be safe
        
        for msg in old_messages:
            try:
                await msg.delete()
                deleted_count += 1
                await asyncio.sleep(0.5) # slow down for individual deletes
            except discord.HTTPException:
                pass
        
        return deleted_count

async def setup(bot):
    await bot.add_cog(Moderation(bot))