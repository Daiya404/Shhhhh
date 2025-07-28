import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import re

class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.replies_file = 'data/auto_replies.json'
        self.replies = self.load_replies()

    # Define the group here
    autoreply = app_commands.Group(name="autoreply", description="[Admin] Manages auto-replies.")

    def load_replies(self):
        if not os.path.exists(self.replies_file):
            default = {}
            with open(self.replies_file, 'w') as f: json.dump(default, f, indent=4)
            return default
        with open(self.replies_file, 'r') as f: return json.load(f)

    def save_replies(self):
        with open(self.replies_file, 'w') as f: json.dump(self.replies, f, indent=4)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        content_lower = message.content.lower()
        for trigger, reply_url in self.replies.items():
            if re.search(r'\b' + re.escape(trigger) + r'\b', content_lower):
                await message.channel.send(reply_url)
                return

    @autoreply.command(name='add', description="[Admin] Add a new auto-reply trigger.")
    @app_commands.describe(trigger="The word that triggers the reply", reply_url="The image/GIF URL to reply with")
    @app_commands.checks.has_permissions(administrator=True)
    async def autoreply_add(self, interaction: discord.Interaction, trigger: str, reply_url: str):
        await interaction.response.defer(ephemeral=True)
        trigger = trigger.lower()
        self.replies[trigger] = reply_url
        self.save_replies()
        await interaction.followup.send(f"Okay, I'll now reply to `{trigger}`.")

    @autoreply.command(name='remove', description="[Admin] Remove an auto-reply trigger.")
    @app_commands.describe(trigger="The trigger word to remove")
    @app_commands.checks.has_permissions(administrator=True)
    async def autoreply_remove(self, interaction: discord.Interaction, trigger: str):
        await interaction.response.defer(ephemeral=True)
        trigger = trigger.lower()
        if trigger in self.replies:
            del self.replies[trigger]
            self.save_replies()
            await interaction.followup.send(f"Hmph. I've removed the auto-reply for `{trigger}`.")
        else:
            await interaction.followup.send("I can't remove something that doesn't exist.")

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoReply(bot))