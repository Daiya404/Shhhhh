# cogs/link_fixer.py
import discord
from discord.ext import commands
import re

class LinkFixer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Regex to find twitter.com or x.com links
        link_pattern = re.compile(r'(https?://(?:www\.)?)(twitter\.com|x\.com)(/\S+)')
        match = link_pattern.search(message.content)

        if match:
            # Reconstruct the link with 'fixupx.com'
            fixed_link = f"{match.group(1)}fixupx.com{match.group(3)}"
            
            # Reconstruct the message content with the new link
            new_content = link_pattern.sub(fixed_link, message.content)

            response_message = f"{message.author.mention}, you posted a broken embed. I fixed it for you. You're welcome.\n\n{new_content}"
            
            # To avoid potential race conditions, send the new message first
            try:
                await message.channel.send(response_message)
                await message.delete()
            except discord.Forbidden:
                print(f"Could not fix link in {message.guild.name} due to missing permissions.")
            except discord.HTTPException as e:
                print(f"An HTTP error occurred while trying to fix a link: {e}")


async def setup(bot):
    await bot.add_cog(LinkFixer(bot))