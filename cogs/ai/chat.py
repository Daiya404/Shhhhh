# cogs/ai/chat.py
import discord
from discord.ext import commands
from discord import app_commands
import logging
from collections import defaultdict
from typing import List, Dict
import asyncio

class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.gemini_service = self.bot.gemini_service
        self.conversation_history: Dict[int, List[Dict]] = defaultdict(list)

    async def _is_feature_enabled(self, interaction: discord.Interaction) -> bool:
        """A local check to see if the ai_chat feature is enabled."""
        feature_manager = self.bot.get_cog("FeatureManager")
        feature_name = "ai_chat"
        
        if not feature_manager or not feature_manager.is_feature_enabled(interaction.guild_id, feature_name):
            await interaction.response.send_message(f"Hmph. The {feature_name.replace('_', ' ').title()} feature is disabled on this server.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="chat", description="Start a new conversation with me (clears your previous chat history).")
    @app_commands.describe(message="Your opening message to start the conversation.")
    async def chat(self, interaction: discord.Interaction, message: str):
        if not await self._is_feature_enabled(interaction):
            return
        if not self.gemini_service or not self.gemini_service.is_ready():
            return await interaction.response.send_message("My AI brain is offline. Try again later.", ephemeral=True)

        await interaction.response.defer()
        
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        self.conversation_history[user_id] = [{"role": "user", "parts": [message]}]
        
        try:
            response_text = await self.gemini_service.generate_chat_response(
                user_message=message,
                conversation_history=self.conversation_history[user_id],
                guild_id=guild_id,
                user_id=user_id
            )

            self.conversation_history[user_id].append({"role": "model", "parts": [response_text]})
            sent_message = await interaction.followup.send(response_text)

            await asyncio.sleep(0.1)  # Ensure message is sent before tracking

            if sent_message and hasattr(sent_message, 'id'):
                self.bot.ai_message_ids.add(sent_message.id)
                self.logger.info(f"Added AI message ID {sent_message.id} to tracking set. Total: {len(self.bot.ai_message_ids)}")
            else:
                self.logger.warning("Failed to get message object from followup.send()")
            
        except Exception as e:
            self.logger.error(f"Chat command failed: {e}", exc_info=True)
            await interaction.followup.send("Sorry, something went wrong with my response.")

async def setup(bot):
    if hasattr(bot, 'gemini_service') and bot.gemini_service and bot.gemini_service.is_ready():
        await bot.add_cog(AIChat(bot))
        logging.getLogger(__name__).info("AIChat cog loaded successfully.")
    else:
        logging.getLogger(__name__).warning("Skipping load of AIChat cog because Gemini Service is not configured or ready.")