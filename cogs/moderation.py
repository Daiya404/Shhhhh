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
        self.CONFIRMATION_DELAY = 3  # Seconds

    @commands.command(name="clear", help="Clear messages between start and end points")
    async def clear_messages(self, ctx, action: Optional[str] = None):
        """Clear messages between start and end points or up to a replied message"""
        
        if not self._has_permission(ctx.author):
            await self._send_temp_message(ctx, "❌ You don't have permission to use this command!", 5)
            return

        if action == "start":
            await self._handle_start_point(ctx)
        elif action == "end":
            await self._handle_end_point(ctx)
        else:
            await self._handle_single_clear(ctx)

    def _has_permission(self, user: discord.Member) -> bool:
        """Check if user has manage messages permission"""
        return user.guild_permissions.manage_messages

    async def _send_temp_message(self, ctx, content: str, delay: int):
        """Send a temporary message that deletes after specified delay"""
        msg = await ctx.send(content)
        await msg.delete(delay=delay)

    async def _handle_start_point(self, ctx):
        """Handle setting the start point for clearing"""
        if not ctx.message.reference or not ctx.message.reference.message_id:
            await self._send_temp_message(
                ctx, 
                "❌ Please reply to a message to set the start point!", 
                5
            )
            return

        try:
            start_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            self.clear_start_points[ctx.channel.id] = start_message.id
            
            confirmation = await ctx.send("✅ Start point set!")
            await asyncio.gather(
                confirmation.delete(delay=self.CONFIRMATION_DELAY),
                ctx.message.delete()
            )
        except discord.NotFound:
            await self._send_temp_message(ctx, "❌ Could not find the replied message!", 5)

    async def _handle_end_point(self, ctx):
        """Handle clearing from start point to end point"""
        if ctx.channel.id not in self.clear_start_points:
            await self._send_temp_message(
                ctx, 
                "❌ No start point set! Use `!clear start` first.", 
                5
            )
            return

        if not ctx.message.reference or not ctx.message.reference.message_id:
            await self._send_temp_message(
                ctx, 
                "❌ Please reply to a message to set the end point!", 
                5
            )
            return

        try:
            start_message_id = self.clear_start_points[ctx.channel.id]
            start_message = await ctx.channel.fetch_message(start_message_id)
            end_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)

            # Ensure proper chronological order
            if start_message.created_at > end_message.created_at:
                start_message, end_message = end_message, start_message

            messages_to_delete = await self._collect_messages_between(
                ctx.channel, 
                start_message, 
                end_message
            )
            messages_to_delete.append(ctx.message)

            if len(messages_to_delete) <= 1:
                await self._send_temp_message(ctx, "❌ No messages found to clear!", 5)
                return

            deleted_count = await self._delete_messages_efficiently(ctx.channel, messages_to_delete)
            
            # Clean up start point
            del self.clear_start_points[ctx.channel.id]
            
            await self._send_temp_message(
                ctx, 
                f"✅ Successfully cleared {deleted_count} messages between start and end points!",
                self.CONFIRMATION_DELAY
            )

        except discord.NotFound:
            await self._send_temp_message(ctx, "❌ Could not find one of the messages!", 5)
        except Exception as e:
            await self._send_temp_message(ctx, f"❌ An error occurred: {str(e)}", 5)

    async def _handle_single_clear(self, ctx):
        """Handle clearing up to a replied message"""
        if not ctx.message.reference or not ctx.message.reference.message_id:
            await self._send_temp_message(
                ctx,
                "❌ Please reply to a message or use:\n"
                "`!clear start` - Set start point (reply to message)\n"
                "`!clear end` - Clear to end point (reply to message)",
                10
            )
            return

        try:
            target_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            
            # More efficient message collection
            messages_to_delete = []
            async for message in ctx.channel.history(
                limit=None, 
                before=ctx.message, 
                after=target_message
            ):
                messages_to_delete.append(message)
            
            messages_to_delete.append(ctx.message)
            
            if len(messages_to_delete) <= 1:
                await self._send_temp_message(ctx, "❌ No messages found to clear!", 5)
                return
            
            deleted_count = await self._delete_messages_efficiently(ctx.channel, messages_to_delete)
            await self._send_temp_message(
                ctx, 
                f"✅ Successfully cleared {deleted_count} messages!",
                self.CONFIRMATION_DELAY
            )
            
        except discord.NotFound:
            await self._send_temp_message(ctx, "❌ Could not find the replied message!", 5)
        except Exception as e:
            await self._send_temp_message(ctx, f"❌ An error occurred: {str(e)}", 5)

    async def _collect_messages_between(
        self, 
        channel: discord.TextChannel, 
        start_message: discord.Message, 
        end_message: discord.Message
    ) -> List[discord.Message]:
        """Collect messages between two points efficiently"""
        messages = []
        
        # Use more efficient approach with limits
        async for message in channel.history(
            limit=None, 
            before=end_message, 
            after=start_message
        ):
            messages.append(message)
        
        # Include the boundary messages
        messages.extend([start_message, end_message])
        return messages

    async def _delete_messages_efficiently(
        self, 
        channel: discord.TextChannel, 
        messages: List[discord.Message]
    ) -> int:
        """Delete messages efficiently using bulk operations where possible"""
        if not messages:
            return 0
        
        deleted_count = 0
        from datetime import timezone
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=self.MESSAGE_AGE_LIMIT)
        
        # Separate messages by age for optimal deletion strategy
        recent_messages = [msg for msg in messages if msg.created_at > cutoff_time]
        old_messages = [msg for msg in messages if msg.created_at <= cutoff_time]
        
        # Bulk delete recent messages in chunks
        deleted_count += await self._bulk_delete_messages(channel, recent_messages)
        
        # Delete old messages individually
        deleted_count += await self._delete_old_messages(old_messages)
        
        return deleted_count

    async def _bulk_delete_messages(
        self, 
        channel: discord.TextChannel, 
        messages: List[discord.Message]
    ) -> int:
        """Bulk delete recent messages in optimal chunks"""
        deleted_count = 0
        
        for i in range(0, len(messages), self.BULK_DELETE_LIMIT):
            chunk = messages[i:i + self.BULK_DELETE_LIMIT]
            try:
                if len(chunk) == 1:
                    await chunk[0].delete()
                else:
                    await channel.delete_messages(chunk)
                deleted_count += len(chunk)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                # Handle individual deletions for failed bulk operations
                for msg in chunk:
                    try:
                        await msg.delete()
                        deleted_count += 1
                    except (discord.Forbidden, discord.NotFound):
                        pass
        
        return deleted_count

    async def _delete_old_messages(self, messages: List[discord.Message]) -> int:
        """Delete old messages individually with error handling"""
        deleted_count = 0
        
        # Use semaphore to limit concurrent deletions
        semaphore = asyncio.Semaphore(10)  # Limit to 10 concurrent deletions
        
        async def delete_single_message(message):
            nonlocal deleted_count
            async with semaphore:
                try:
                    await message.delete()
                    deleted_count += 1
                except (discord.NotFound, discord.Forbidden):
                    pass
        
        # Delete messages concurrently but with limits
        tasks = [delete_single_message(msg) for msg in messages]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        return deleted_count

async def setup(bot):
    await bot.add_cog(Moderation(bot))