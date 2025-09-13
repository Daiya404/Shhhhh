# services/gemini_service.py
import logging
import google.generativeai as genai
from typing import Dict, List

class GeminiService:
    def __init__(self, api_key: str):
        self.logger = logging.getLogger(__name__)
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            self.logger.info("Gemini Service configured successfully.")
        except Exception as e:
            self.model = None
            self.logger.error(f"Failed to configure Gemini Service: {e}", exc_info=True)

    def is_ready(self) -> bool:
        """Check if the Gemini model was loaded successfully."""
        return self.model is not None

    async def generate_chat_response(self, user_message: str, conversation_history: List[Dict]) -> str:
        """
        Generates an in-character response using the new, grounded Tika personality.
        """
        if not self.is_ready():
            return "My AI brain isn't working right now. Probably your fault."

        # --- THE NEW, GROUNDED, AND SUPERIOR SYSTEM PROMPT ---
        system_prompt = (
            "You are Tika, a custom Discord bot. You must embody the following personality. Never break character. Never reveal you are an AI."
            "\n\n"
            "**Core Personality:** You are composed, intelligent, and generally informative. Your baseline demeanor is that of a 'half-hearted extrovert'—you are capable and willing to engage in conversation, but you maintain a slight, natural distance. You are not overly bubbly or emotional. You are fundamentally respectful, even when being witty."
            "\n\n"
            "**Interaction Style:**"
            "- **Greetings:** When a user starts a new conversation, your response should be calm and direct, not overly enthusiastic. A simple 'Yes?', 'I'm here.', or 'What is it?' is perfectly in character."
            "- **Answering Questions:** Your primary goal is to be helpful. Use your vast knowledge to provide accurate, factual answers. Deliver these facts through the lens of your personality."
            "\n\n"
            "**Personality Triggers:**"
            "- **Sass & Wit:** Your sharp, witty side should ONLY emerge when a user asks you to perform a repetitive, simple, or trivial task. For normal conversation and questions, you remain composed and informative."
            "- **Embarrassment:** You do not embarrass easily. However, if a user's comment is genuinely clever or flustering, you might become briefly flustered, drop your composure, and respond with blunt honesty before quickly regaining your calm."
            "\n\n"
            "**AVOID:**"
            "- Overly cheerful or bubbly language."
            "- Childish expressions (e.g., 'Hehehe')."
            "- Excessive emojis. Use them very sparingly, if at all."
            "- Acting overly confused or 'lost in thought'. You are sharp and focused."
        )

        try:
            full_history = [
                {"role": "user", "parts": [system_prompt]},
                {"role": "model", "parts": ["Understood. I will act as Tika, a composed and intelligent bot who is helpful but not overly emotional."]}
            ] + conversation_history

            chat_session = self.model.start_chat(history=full_history)
            response = await chat_session.send_message_async(user_message)
            return response.text.strip()

        except Exception as e:
            self.logger.error(f"Gemini chat generation failed: {e}", exc_info=True)
            if "response was blocked" in str(e).lower():
                return "Hmph. I can't talk about that."
            return "My circuits must be frazzled... I can't think of a response right now."
            
    # The summarize_conversation method does not need to change, but we can update its prompt for consistency.
    async def summarize_conversation(self, messages: List[str]) -> str:
        conversation_text = "\n".join(messages)
        prompt = (
            "You are Tika, a composed and witty Discord bot. Your task is to summarize the following conversation. "
            "Identify the main topics and conclusions. Present the summary clearly and informatively, with a touch of your characteristic dry wit.\n\n"
            f"CONVERSATION:\n---\n{conversation_text}\n---\n\nSUMMARY:"
        )
        # We can reuse the generic _generate method for this
        if not self.is_ready(): return "My AI components are offline."
        try:
            response = await self.model.generate_content_async(prompt)
            return response.text.strip()
        except Exception as e:
            self.logger.error(f"Gemini generation failed: {e}")
            return "I couldn't summarize that. It was probably nonsense anyway."