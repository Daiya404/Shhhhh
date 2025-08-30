import discord
from discord import app_commands
import re

from plugins.base_plugin import BasePlugin
from shared.utils.decorators import is_bot_admin

class MessageAutomationPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "message_automation"

    def __init__(self, bot):
        super().__init__(bot)
        # Link fixer regex
        self.link_pattern = re.compile(
            r'https?:\/\/(?:www\.)?(?:twitter|x)\.com\/[a-zA-Z0-9_]+\/status\/[0-9]+'
        )
        # Auto-reply regex cache
        self.reply_regex_cache: dict[int, re.Pattern] = {}

    async def _build_reply_regex_for_guild(self, guild_id: int):
        """Builds and caches the auto-reply regex for a guild."""
        config = await self.db.get_guild_data(guild_id, self.name)
        triggers_data = config.get("auto_replies", {})
        all_triggers = list(triggers_data.keys())
        if not all_triggers:
            self.reply_regex_cache.pop(guild_id, None)
            return
        pattern = r'\b(' + '|'.join(re.escape(word) for word in all_triggers) + r')\b'
        self.reply_regex_cache[guild_id] = re.compile(pattern, re.IGNORECASE)

    async def on_message(self, message: discord.Message) -> bool:
        if not message.guild or not message.content or message.author.bot:
            return False

        # --- Link Fixer Logic ---
        config = await self.db.get_guild_data(message.guild.id, self.name)
        link_fixer_settings = config.get("link_fixer", {"enabled": True, "opt_out": []})
        if link_fixer_settings["enabled"] and message.author.id not in link_fixer_settings["opt_out"]:
            if self.link_pattern.search(message.content):
                fixed_content = message.content.replace("twitter.com", "vxtwitter.com").replace("x.com", "vxtwitter.com")
                if fixed_content != message.content:
                    try:
                        # Simplified send-and-delete logic
                        await message.channel.send(f"Fixed link for {message.author.mention}:\n{fixed_content}")
                        await message.delete()
                        return True # Message handled
                    except discord.Forbidden:
                        self.logger.warning(f"Missing permissions to fix link in {message.channel.name}")
                    except Exception as e:
                        self.logger.error(f"Failed to fix link: {e}")

        # --- Auto-Reply Logic ---
        if message.guild.id not in self.reply_regex_cache:
            await self._build_reply_regex_for_guild(message.guild.id)

        guild_regex = self.reply_regex_cache.get(message.guild.id)
        if guild_regex:
            match = guild_regex.search(message.content)
            if match:
                triggered_word = match.group(1).lower()
                auto_replies = config.get("auto_replies", {})
                reply_content = auto_replies.get(triggered_word)
                if reply_content:
                    await message.reply(reply_content, mention_author=False)
                    return True # Message handled

        return False

    # --- Link Fixer Commands ---
    fixer_group = app_commands.Group(name="linkfixer", description="Manage the automatic link fixer.")

    @fixer_group.command(name="toggle", description="[Admin] Turn the link fixer ON or OFF for the server.")
    @is_bot_admin()
    async def toggle_fixer(self, interaction: discord.Interaction, enabled: bool):
        config = await self.db.get_guild_data(interaction.guild_id, self.name)
        link_fixer_settings = config.setdefault("link_fixer", {"enabled": True, "opt_out": []})
        link_fixer_settings["enabled"] = enabled
        await self.db.save_guild_data(interaction.guild_id, self.name, config)
        status = "ON" if enabled else "OFF"
        await interaction.response.send_message(f"Link fixer is now **{status}** for the server.", ephemeral=True)

    # --- Auto-Reply Commands (`/nga` equivalent) ---
    reply_group = app_commands.Group(name="autoreply", description="Manage automatic replies to trigger words.")

    @reply_group.command(name="add", description="[Admin] Set up a new trigger word with a reply.")
    @app_commands.describe(trigger="The word to listen for.", reply="The text or URL to reply with.")
    @is_bot_admin()
    async def add_reply(self, interaction: discord.Interaction, trigger: str, reply: str):
        trigger_key = trigger.lower().strip()
        config = await self.db.get_guild_data(interaction.guild.id, self.name)
        replies = config.setdefault("auto_replies", {})

        if trigger_key in replies:
            return await interaction.response.send_message("That trigger already exists.", ephemeral=True)

        replies[trigger_key] = reply
        await self.db.save_guild_data(interaction.guild.id, self.name, config)
        await self._build_reply_regex_for_guild(interaction.guild.id)
        await interaction.response.send_message(f"Fine. If anyone says `{trigger}`, I'll reply with that.", ephemeral=True)

    # --- ADD A NEW COMMAND TO REMOVE REPLIES ---
    @reply_group.command(name="remove", description="[Admin] Remove an auto-reply trigger.")
    @app_commands.describe(trigger="The trigger word to remove.")
    @is_bot_admin() # <-- ADDING DECORATOR HERE
    async def remove_reply(self, interaction: discord.Interaction, trigger: str):
        trigger_key = trigger.lower().strip()
        config = await self.db.get_guild_data(interaction.guild.id, self.name)
        replies = config.get("auto_replies", {})

        if trigger_key not in replies:
            return await interaction.response.send_message("I wasn't blocking that word to begin with.", ephemeral=True)

        del replies[trigger_key]
        await self.db.save_guild_data(interaction.guild.id, self.name, config)
        await self._build_reply_regex_for_guild(interaction.guild.id)
        await interaction.response.send_message(f"Fine, I've removed that word from the blocklist.", ephemeral=True)