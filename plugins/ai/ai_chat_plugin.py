# --- plugins/ai/ai_chat_plugin.py ---

import discord
from discord import app_commands
import os
import aiohttp
from plugins.base_plugin import BasePlugin

class AIChatPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "ai_chat"

    def __init__(self, bot):
        super().__init__(bot)
        self.http_session = aiohttp.ClientSession()
        self.api_key = os.getenv("GEMINI_API_KEY")

    async def cog_unload(self):
        await self.http_session.close()

    async def _call_gemini_api(self, prompt: str) -> str:
        if not self.api_key:
            return "My AI brain is missing its API key. An admin needs to set the `GEMINI_API_KEY` in the `.env` file."

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={self.api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        try:
            async with self.http_session.post(url, json=payload, timeout=60.0) as response:
                response.raise_for_status()
                data = await response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            self.logger.error(f"Error calling Gemini API: {e}")
            return "Sorry, I had a little trouble thinking. Could you try again?"

    async def on_message(self, message: discord.Message) -> bool:
        # Check if the bot was mentioned and is not a reply
        if not message.guild or not self.bot.user.mentioned_in(message) or message.reference:
            return False

        config = await self.db.get_guild_data(message.guild.id, self.name)
        char_config = config.get("character", {
            "name": "Tika",
            "personality": "Sassy and efficient."
        })

        prompt = (
            f"You are a Discord chatbot named {char_config['name']}. "
            f"Your personality is: {char_config['personality']}. "
            f"Keep your responses concise for chat. The user '{message.author.display_name}' just said: "
            f"'{message.clean_content}'"
        )
        
        async with message.channel.typing():
            response_text = await self._call_gemini_api(prompt)
            await message.reply(response_text, mention_author=False)
        
        return True # Message was handled

    # --- AI Commands ---
    chatbot_group = app_commands.Group(name="chatbot", description="Commands to manage Tika's AI brain.")

    @chatbot_group.command(name="summarize", description="Use AI to summarize recent messages in this channel.")
    @app_commands.describe(count="The number of messages to summarize (max 100).")
    async def summarize(self, interaction, count: app_commands.Range[int, 5, 100]):
        await interaction.response.defer(ephemeral=True)
        history = [f"{m.author.display_name}: {m.clean_content}" async for m in interaction.channel.history(limit=count)]
        history.reverse()
        chat_log = "\n".join(history)

        prompt = (
            "You are a helpful assistant. Summarize the following Discord chat log. "
            "Provide a concise, bulleted summary of the main topics and conclusions. "
            f"Ignore casual chatter.\n\nChat Log:\n---\n{chat_log}\n---"
        )
        summary = await self._call_gemini_api(prompt)
        embed = discord.Embed(title=f"Summary of the Last {count} Messages", description=summary, color=discord.Color.blue())
        await interaction.followup.send(embed=embed)