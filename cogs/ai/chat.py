# cogs/ai/chat.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
from collections import defaultdict
from typing import List, Dict

class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.gemini_service = self.bot.gemini_service
        self.conversation_history: Dict[int, List[Dict]] = defaultdict(list)

    @app_commands.command(name="chat", description="Start a new conversation with me (clears your previous chat history).")
    @app_commands.describe(message="Your opening message to start the conversation.")
    async def chat(self, interaction: discord.Interaction, message: str):
        feature_manager = self.bot.get_cog("FeatureManager")
        if feature_manager and not feature_manager.is_feature_enabled(interaction.guild_id, "ai_chat"):
            return await interaction.response.send_message("The AI Chat feature is disabled on this server.", ephemeral=True)

        if not self.gemini_service or not self.gemini_service.is_ready():
            return await interaction.response.send_message("My AI brain is offline. Try again later.", ephemeral=True)

        await interaction.response.defer()
        user_id = interaction.user.id
        
        # This command starts a NEW conversation
        self.conversation_history[user_id] = [{"role": "user", "parts": [message]}]
        
        async with interaction.channel.typing():
            # --- THIS IS THE FIX ---
            # We now pass BOTH the new message AND the history, as required.
            response_text = await self.gemini_service.generate_chat_response(
                user_message=message,
                conversation_history=self.conversation_history[user_id]
            )
            # --- END OF FIX ---

        self.conversation_history[user_id].append({"role": "model", "parts": [response_text]})
        await interaction.followup.send(response_text)

async def setup(bot):
    if hasattr(bot, 'gemini_service') and bot.gemini_service and bot.gemini_service.is_ready():
        await bot.add_cog(AIChat(bot))
    else:
        logging.getLogger(__name__).warning("Skipping load of AIChat cog because Gemini Service is not configured.")