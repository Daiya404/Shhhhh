import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional

# Import the chatbot cog to access its brain
from .chatbot import Chatbot, ChatbotBrain

# --- Personality Responses ---
PERSONALITY = {
    "summary_start": "Fine, I'll catch you up. Reading the last {count} messages... This might take a moment.",
    "summary_too_many": "I'm not reading that much. Keep it to {limit} messages or less.",
    "ai_brain_error": "My AI brain isn't working right now. Try again later."
}

class AIFeatures(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # This will be populated on_ready
        self.chatbot_cog: Optional[Chatbot] = None

    @commands.Cog.listener()
    async def on_ready(self):
        """Get the Chatbot cog once the bot is ready."""
        # It might take a moment for other cogs to be available
        await asyncio.sleep(1) 
        self.chatbot_cog = self.bot.get_cog("Chatbot")
        if not self.chatbot_cog or not self.chatbot_cog.chatbot_brain:
            self.logger.critical("CRITICAL: Chatbot cog or brain not found. AI features will not function.")

    # --- Core Logic for Traffic Cop ---
    async def handle_ai_mention(self, message: discord.Message) -> bool:
        """Handles mentions and decides if it's a chatbot interaction."""
        if not self.chatbot_cog or not self.chatbot_cog.chatbot_brain:
            return False
        
        # Only trigger if the bot is directly mentioned and it's not a reply
        if self.bot.user.mentioned_in(message) and not message.reference:
            user_input = message.clean_content.strip()
            author_name = message.author.display_name
            
            # --- NEW: Fetch conversation context ---
            context_history = []
            async for old_message in message.channel.history(limit=6, before=message):
                # We want 5 previous messages, limit is 6 to include the current one in the async for
                context_history.append(f"{old_message.author.display_name}: {old_message.clean_content}")
            context_history.reverse() # Order from oldest to newest
            
            async with message.channel.typing():
                response = await self.chatbot_cog.chatbot_brain.get_chat_response(
                    user_input=user_input, 
                    author_name=author_name, 
                    channel_id=message.channel.id,
                    history_override=context_history # Pass the fetched context
                )
                await message.reply(response)
            return True # We handled the message
        return False

    # --- AI Commands ---
    @app_commands.command(name="summarize", description="Use AI to summarize recent messages in this channel.")
    @app_commands.describe(count="The number of messages to summarize (max 100).")
    async def summarize(self, interaction: discord.Interaction, count: app_commands.Range[int, 5, 100]):
        if not self.chatbot_cog or not self.chatbot_cog.chatbot_brain:
            return await interaction.response.send_message(PERSONALITY["ai_brain_error"], ephemeral=True)

        await interaction.response.send_message(PERSONALITY["summary_start"].format(count=count), ephemeral=True)

        history = [f"{m.author.display_name}: {m.clean_content}" async for m in interaction.channel.history(limit=count)]
        history.reverse()
        
        chat_log = "\n".join(history)
        prompt = (
            "You are a helpful assistant named Tika. Your task is to summarize a Discord chat log. "
            "Analyze the following conversation and provide a concise, bulleted summary of the main topics and conclusions. "
            "Ignore casual chatter and focus on the key points.\n\n"
            f"Chat Log:\n---\n{chat_log}\n---"
        )
        
        # Use the brain's raw API call for this specialized task
        summary = await self.chatbot_cog.chatbot_brain._call_gemini_api(prompt)
        
        embed = discord.Embed(
            title=f"Summary of the Last {count} Messages",
            description=summary,
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    # We need asyncio for the on_ready sleep
    import asyncio
    await bot.add_cog(AIFeatures(bot))