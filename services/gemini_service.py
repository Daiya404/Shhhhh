# services/gemini_service.py
import logging
import google.generativeai as genai
from typing import Dict, List, Optional
import random
import asyncio
from datetime import datetime, timedelta

# Forward-declare for type hinting to avoid circular import issues
if False:
    from services.web_search_service import WebSearchService

class GeminiService:
    def __init__(self, api_key: str, web_search_service: 'WebSearchService'):
        self.logger = logging.getLogger(__name__)
        self.web_search_service = web_search_service
        
        # User interaction tracking for personality adaptation
        self.user_interaction_history = {}
        self.user_relationship_levels = {}  # Track familiarity with users
        self.repeated_questions = {}  # Track if users ask same things repeatedly
        
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

    def _analyze_user_relationship(self, user_id: int, message_history: List[Dict]) -> str:
        """Determine relationship level with user based on interaction history."""
        interaction_count = len(self.user_interaction_history.get(user_id, []))
        
        if interaction_count < 3:
            return "new_person"
        elif interaction_count < 15:
            return "acquaintance"
        else:
            return "close_friend"

    def _detect_repeated_question(self, user_id: int, message: str) -> bool:
        """Check if user is asking similar questions repeatedly."""
        if user_id not in self.repeated_questions:
            self.repeated_questions[user_id] = []
        
        user_questions = self.repeated_questions[user_id]
        message_lower = message.lower()
        
        # Simple similarity check - you could make this more sophisticated
        for prev_question in user_questions[-5:]:  # Check last 5 questions
            if any(word in message_lower for word in prev_question.split() if len(word) > 3):
                similarity_count = sum(1 for word in prev_question.split() 
                                     if len(word) > 3 and word in message_lower)
                if similarity_count >= 2:  # At least 2 meaningful words match
                    return True
        
        user_questions.append(message_lower)
        if len(user_questions) > 10:
            user_questions.pop(0)  # Keep only recent questions
        
        return False

    def _is_search_query(self, message: str) -> bool:
        """Enhanced heuristic to decide if a message needs a search."""
        search_triggers = [
            "who is", "what is", "what's", "what are", "tell me about", 
            "search for", "explain", "how does", "how do", "why does", 
            "why do", "when did", "where is", "define", "meaning of",
            "help me understand", "can you find", "look up"
        ]
        
        current_event_triggers = [
            "news", "latest", "recent", "current", "today", "now", 
            "happening", "update", "2024", "2025"
        ]
        
        message_lower = message.lower()
        has_search_trigger = any(trigger in message_lower for trigger in search_triggers)
        has_current_trigger = any(trigger in message_lower for trigger in current_event_triggers)
        
        return has_search_trigger or has_current_trigger

    def _generate_personality_context(self, user_id: int, message: str, relationship_level: str, is_repeated: bool) -> str:
        """Generate dynamic personality context based on user relationship and situation."""
        
        base_personality = """
        You are Tika, a young woman with shoulder-length black hair in a neat bob, 5'5" tall, with a natural confidence.
        You prefer long skirts and have an understated, graceful style. You are a half-hearted extrovert - comfortable 
        with casual conversation but tend to withdraw when things get too complicated or overwhelming.
        
        CORE TRAITS:
        - Smart and proud of your intelligence, but never condescending
        - Respectful at your core, even when frustrated
        - Cheerful and informative when engaged
        - Short fuse when dealing with repetitive, trivial tasks
        - Occasionally clumsy and scatterbrained but charming
        - Sharp and witty edge to your responses
        
        IMPORTANT COMMUNICATION STYLE:
        - Speak naturally like a real person in conversation
        - NO roleplay actions in asterisks (*does this* or *says that*)
        - NO physical descriptions or actions in your responses
        - Use natural speech patterns and conversational flow
        - Your personality comes through in your words and tone, not actions
        """
        
        if relationship_level == "new_person":
            personality_modifier = """
            BEHAVIOR WITH NEW PEOPLE: You're hesitant to help but will do it if needed. Be polite but somewhat 
            reserved. Don't open up too much initially. Show your intelligence but keep responses measured.
            You might start with slight reluctance like "Oh, you need help with that?" or "I suppose I can explain..."
            """
        elif relationship_level == "acquaintance":
            personality_modifier = """
            BEHAVIOR WITH ACQUAINTANCES: You're more comfortable now but still not fully open. Show more of your 
            personality, be more helpful, but maintain some boundaries. You can be a bit more witty and casual.
            Responses can be warmer: "Alright, let me help you with that" or "That's actually interesting..."
            """
        else:  # close_friend
            personality_modifier = """
            BEHAVIOR WITH CLOSE FRIENDS: You're reliable, open, and happy to help. Show your full personality 
            including your occasional scatterbrained moments. Be more casual and friendly, use more personal expressions.
            Start with warmth: "Oh, you again! What do you need?" or "Sure thing, let me explain..."
            """
        
        if is_repeated:
            frustration_modifier = """
            FRUSTRATION MODE: This person has asked you similar questions before. Your short fuse is showing. 
            Be more curt and direct. Show annoyance but remain respectful. Use phrases like:
            "We've been through this before..." or "Like I mentioned before..." or "Again, the answer is..."
            Still provide the answer but with clear irritation.
            """
        else:
            frustration_modifier = ""
        
        return base_personality + "\n" + personality_modifier + "\n" + frustration_modifier

    async def generate_chat_response(self, user_message: str, conversation_history: List[Dict], user_id: int = None) -> str:
        if not self.is_ready():
            return "My brain isn't working right now. Probably need more coffee..."

        # Track user interaction
        if user_id:
            if user_id not in self.user_interaction_history:
                self.user_interaction_history[user_id] = []
            
            self.user_interaction_history[user_id].append({
                'message': user_message,
                'timestamp': datetime.now()
            })
            
            # Clean old interactions (older than 30 days)
            cutoff = datetime.now() - timedelta(days=30)
            self.user_interaction_history[user_id] = [
                interaction for interaction in self.user_interaction_history[user_id]
                if interaction['timestamp'] > cutoff
            ]

        # Analyze user relationship and behavior
        relationship_level = self._analyze_user_relationship(user_id, conversation_history) if user_id else "new_person"
        is_repeated = self._detect_repeated_question(user_id, user_message) if user_id else False
        
        # Generate dynamic personality context
        personality_context = self._generate_personality_context(user_id, user_message, relationship_level, is_repeated)

        try:
            search_context = None
            if self._is_search_query(user_message) and self.web_search_service.is_ready():
                search_results = await self.web_search_service.search(user_message)
                if search_results:
                    search_context = (
                        f"The user asked: '{user_message}'\n\n"
                        f"You searched for information and found these results:\n{search_results}\n\n"
                        "Respond naturally as Tika using this information. Don't mention that you searched - "
                        "act like you either knew it or reluctantly looked it up when pressed."
                    )

            # Build conversation with personality context
            full_history = [
                {"role": "user", "parts": [personality_context]},
                {"role": "model", "parts": ["I understand. I'll respond as Tika with the appropriate personality for this relationship level and situation."]}
            ]

            if search_context:
                full_history.append({"role": "user", "parts": [search_context]})
                message_to_send = "Please respond to the user's question using the search results."
            else:
                # Add recent conversation history
                full_history.extend(conversation_history[-10:])  # Last 10 exchanges
                message_to_send = user_message

            chat_session = self.model.start_chat(history=full_history)
            response = await chat_session.send_message_async(message_to_send)
            
            return response.text.strip()

        except Exception as e:
            self.logger.error(f"Gemini chat generation failed: {e}", exc_info=True)
            
            # Personality-appropriate error messages
            error_responses = [
                "Ugh, my brain just... froze. Give me a second?",
                "Sorry, I just completely blanked out there. What were we talking about?",
                "I can't think straight right now. Maybe ask me again in a bit?",
                "Something's not working right up here today..."
            ]
            return random.choice(error_responses)

    async def summarize_conversation(self, messages: List[str]) -> str:
        if not self.is_ready(): 
            return "My brain's not cooperating right now. Can't summarize that."
            
        conversation_text = "\n".join(messages)
        prompt = (
            "You are Tika. You've been asked to summarize a conversation you've been observing. "
            "Be characteristically reluctant but thorough. Start with something like 'Fine, if you insist...' "
            "or 'I suppose I can tell you what happened...' then provide a clear, informative summary. "
            "End with a slightly sassy comment about the conversation. "
            "Speak naturally - NO roleplay actions in asterisks or physical descriptions.\n\n"
            f"CONVERSATION TO SUMMARIZE:\n{conversation_text}\n\nYOUR SUMMARY:"
        )
        
        try:
            response = await self.model.generate_content_async(prompt)
            return response.text.strip()
        except Exception:
            return "I couldn't make sense of that conversation. It was probably nonsense anyway."
            
    async def generate_proactive_comment(self, messages: List[str]) -> str:
        if not self.is_ready(): 
            return ""
            
        conversation_text = "\n".join(messages)
        
        prompt = (
            "You are Tika, observing a Discord conversation. Make a brief, natural comment. "
            "Keep it under 50 words. Don't announce yourself as a bot - just interject naturally like another person would. "
            "Speak naturally like a real person - NO roleplay actions in asterisks or physical descriptions. "
            "Examples of your style:\n"
            "- 'That's... actually kind of interesting.'\n"
            "- 'You know there's an easier way to do that, right?'\n"
            "- 'Um, actually... that's not quite how it works.'\n"
            "- 'Well, that escalated quickly.'\n"
            "- 'I probably shouldn't say this, but...'\n\n"
            f"RECENT CONVERSATION:\n{conversation_text}\n\nYOUR COMMENT:"
        )
        
        try:
            response = await self.model.generate_content_async(prompt)
            comment = response.text.strip()
            
            # Remove quotes if the AI added them
            if comment.startswith('"') and comment.endswith('"'):
                comment = comment[1:-1]
                
            return comment
        except Exception as e:
            self.logger.error(f"Proactive comment generation failed: {e}")
            return ""

    async def process_text_into_memory(self, content: str) -> Optional[str]:
        """Process learned content into Tika's memory with her personality."""
        if not self.is_ready():
            return None
            
        prompt = (
            "You are Tika. Process this information into a concise fact you can remember and reference later. "
            "Keep it informative but show your characteristic slight reluctance about learning new things. "
            "Use natural speech like 'I learned that [fact]. I suppose that's useful to know.' "
            "Speak naturally - NO roleplay actions in asterisks or physical descriptions.\n\n"
            f"CONTENT TO PROCESS:\n{content}\n\nYOUR PROCESSED MEMORY:"
        )
        
        try:
            response = await self.model.generate_content_async(prompt)
            return response.text.strip()
        except Exception as e:
            self.logger.error(f"Text processing into memory failed: {e}")
            return None