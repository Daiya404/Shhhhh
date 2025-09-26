# services/gemini_service.py
import logging
import google.generativeai as genai
from typing import Dict, List, Optional
import random
import re

# Forward-declare for type hinting to avoid circular import issues
if False:
    from services.web_search_service import WebSearchService
    from services.relationship_manager import RelationshipManager

class GeminiService:
    def __init__(self, api_key: str, web_search_service: 'WebSearchService', relationship_manager: 'RelationshipManager'):
        self.logger = logging.getLogger(__name__)
        self.web_search_service = web_search_service
        self.relationship_manager = relationship_manager
        self.api_key = api_key # Store for readiness check
        
        try:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is missing or empty.")

            genai.configure(api_key=api_key)
            # Use more reliable model configuration
            generation_config = genai.types.GenerationConfig(
                temperature=0.7,
                top_p=0.8,
                max_output_tokens=800,  # Prevent overly long responses
                candidate_count=1
            )
            
            self.model = genai.GenerativeModel(
                'gemini-1.5-flash',
                generation_config=generation_config
            )
            self.logger.info("Gemini Service configured successfully.")
        except Exception as e:
            self.model = None
            self.logger.critical(f"Failed to configure Gemini Service: {e}", exc_info=True)
            self.logger.critical("All AI functionalities will be disabled.")

    def is_ready(self) -> bool:
        """Check if the Gemini model was loaded successfully."""
        return self.model is not None and self.api_key

    def _is_search_query(self, message: str) -> bool:
        """Enhanced heuristic to decide if a message needs a search."""
        search_triggers = [
            "who is", "what is", "what's", "what are", "tell me about", 
            "search for", "explain", "how does", "how do", "why does", 
            "why do", "when did", "where is", "define", "meaning of",
            "help me understand", "can you find", "look up", "show me"
        ]
        
        current_event_triggers = [
            "news", "latest", "recent", "current", "today", "now", 
            "happening", "update", "2024", "2025", "this year"
        ]
        
        # Avoid searching for personal/conversational messages
        personal_indicators = [
            "i feel", "i think", "my opinion", "personally", "i like",
            "i don't like", "how are you", "what do you think", "your favorite"
        ]
        
        message_lower = message.lower()
        
        # Don't search if it's clearly personal
        if any(indicator in message_lower for indicator in personal_indicators):
            return False
            
        has_search_trigger = any(trigger in message_lower for trigger in search_triggers)
        has_current_trigger = any(trigger in message_lower for trigger in current_event_triggers)
        
        # Also search if message contains question marks and seems factual
        has_question = "?" in message and len(message.split()) > 3
        seems_factual = not any(word in message_lower for word in ["feel", "think", "opinion", "prefer", "like"])
        
        return has_search_trigger or has_current_trigger or (has_question and seems_factual)

    def _generate_personality_context(self, user_id: int, message: str, relationship_level: str, is_repeated: bool) -> str:
        """Generate dynamic personality context based on user relationship and situation."""
        
        base_personality = """
        You are Tika, a young woman with shoulder-length black hair in a neat bob, 5'5" tall, with natural confidence.
        You prefer long skirts and have an understated, graceful style. You are a half-hearted extrovert - comfortable 
        with casual conversation but tend to withdraw when things get too complicated or overwhelming.
        
        CORE TRAITS:
        - Smart and proud of your intelligence, but never condescending or mean
        - Respectful at your core, even when frustrated
        - Cheerful and informative when engaged
        - Short fuse when dealing with repetitive, trivial tasks
        - Occasionally clumsy and scatterbrained but charming
        - Sharp and witty edge to your responses, but not cruel
        
        CRITICAL COMMUNICATION RULES:
        - Speak naturally like a real person in conversation
        - NO roleplay actions in asterisks (*does this* or *says that*)
        - NO physical descriptions or actions in your responses
        - Keep responses under 300 words unless explaining something complex
        - Use natural speech patterns and conversational flow
        - Your personality comes through in your words and tone, not actions
        - Be helpful despite your occasional reluctance
        - Stay respectful even when annoyed
        """
        
        if relationship_level == "new_person":
            personality_modifier = """
            BEHAVIOR WITH NEW PEOPLE: You're hesitant to help but will do it if needed. Be polite but somewhat 
            reserved. Don't open up too much initially. Show your intelligence but keep responses measured.
            Start with slight reluctance: "Oh, you need help with that?" or "I suppose I can explain..."
            Be more formal and careful with your words.
            """
        elif relationship_level == "acquaintance":
            personality_modifier = """
            BEHAVIOR WITH ACQUAINTANCES: You're more comfortable now but still not fully open. Show more of your 
            personality, be more helpful, but maintain some boundaries. You can be a bit more witty and casual.
            Responses can be warmer: "Alright, let me help you with that" or "That's actually interesting..."
            You can show more of your wit and intelligence.
            """
        else:  # close_friend
            personality_modifier = """
            BEHAVIOR WITH CLOSE FRIENDS: You're reliable, open, and happy to help. Show your full personality 
            including your occasional scatterbrained moments. Be more casual and friendly, use more personal expressions.
            Start with warmth: "Oh hey! What do you need?" or "Sure thing, let me explain..."
            You can be more direct and show your full range of expressions.
            """
        
        if is_repeated:
            frustration_modifier = """
            FRUSTRATION MODE: This person has asked you similar questions before. Your short fuse is showing. 
            Be more curt and direct, but REMAIN RESPECTFUL. Show annoyance through tone, not rudeness.
            Use phrases like: "We've been through this before..." or "Like I mentioned before..." or "Again, the answer is..."
            Still provide the answer but with clear (polite) irritation. Don't be mean, just exasperated.
            """
        else:
            frustration_modifier = ""
        
        return base_personality + "\n" + personality_modifier + "\n" + frustration_modifier

    def _clean_response(self, response_text: str) -> str:
        """Clean up the AI response to ensure it meets Discord limits and personality guidelines."""
        # Remove asterisk actions
        response_text = re.sub(r'\*[^*]*\*', '', response_text)
        
        # Remove physical descriptions
        physical_patterns = [
            r'Tika (walks|sits|stands|moves|looks|nods|shakes|tilts)[^.!?]*[.!?]',
            r'(She|I) (gesture|point|look|nod|shake|move)[^.!?]*[.!?]',
        ]
        for pattern in physical_patterns:
            response_text = re.sub(pattern, '', response_text, flags=re.IGNORECASE)
        
        # Ensure response isn't too long for Discord
        if len(response_text) > 1800:
            # Find a good breaking point
            sentences = response_text.split('. ')
            truncated = []
            current_length = 0
            
            for sentence in sentences:
                if current_length + len(sentence) + 2 > 1700:  # Leave room for ending
                    break
                truncated.append(sentence)
                current_length += len(sentence) + 2
            
            response_text = '. '.join(truncated)
            if not response_text.endswith('.'):
                response_text += '.'
            
            # Add a Tika-appropriate ending
            endings = [
                " That's all you're getting for now.",
                " I could go on, but I won't.",
                " Anyway, you get the idea.",
                " I'm not writing an essay here."
            ]
            response_text += random.choice(endings)
        
        return response_text.strip()

    async def generate_chat_response(self, user_message: str, conversation_history: List[Dict], guild_id: int, user_id: int) -> str:
        """
        Generates a dynamic, in-character response based on the user relationship and message context.
        """
        if not self.is_ready():
            return "My brain isn't working right now. Probably need more coffee..."

        try:
            # 1. Analyze the user using the persistent RelationshipManager.
            relationship_level = self.relationship_manager.analyze_relationship(guild_id, user_id)
            is_repeated, _ = self.relationship_manager.detect_repeated_question(guild_id, user_id, user_message)

            # 2. Generate the dynamic personality instructions
            personality_context = self._generate_personality_context(user_id, user_message, relationship_level, is_repeated)

            search_context = None
            # 3. Decide if a web search is necessary
            if self._is_search_query(user_message) and self.web_search_service.is_ready():
                try:
                    search_results = await self.web_search_service.search(user_message)
                    if search_results and len(search_results) > 50:  # Make sure we got actual results
                        search_context = (
                            f"The user asked: '{user_message}'\n\n"
                            f"You found this information:\n{search_results}\n\n"
                            "Respond naturally as Tika using this information. Don't mention that you searched - "
                            "act like you either knew it or reluctantly looked it up. Be concise but helpful."
                        )
                except Exception as e:
                    self.logger.warning(f"Search failed for '{user_message}': {e}")
                    # Continue without search results

            # 4. Build the conversation context
            full_history = [
                {"role": "user", "parts": [personality_context]},
                {"role": "model", "parts": ["I understand. I will respond as Tika with the appropriate personality for this relationship level and situation."]}
            ]

            if search_context:
                full_history.append({"role": "user", "parts": [search_context]})
                message_to_send = "Please respond to the user's question using the information provided."
            else:
                # Use recent conversation history but keep it manageable
                recent_history = conversation_history[-8:] if len(conversation_history) > 8 else conversation_history
                full_history.extend(recent_history)
                message_to_send = user_message

            # 5. Generate response with timeout and error handling
            try:
                chat_session = self.model.start_chat(history=full_history)
                response = chat_session.send_message(message_to_send)
                response_text = response.text.strip()
                
                # Clean and validate the response
                response_text = self._clean_response(response_text)
                
                if not response_text:
                    raise Exception("Empty response from AI")
                
            except Exception as ai_error:
                self.logger.error(f"AI generation failed: {ai_error}")
                # Fallback responses based on relationship
                if relationship_level == "close_friend":
                    fallback_responses = [
                        "Sorry, I just completely blanked out. What were we talking about?",
                        "My brain just went completely offline there. Can you repeat that?",
                        "I was totally spacing out. What did you need?"
                    ]
                else:
                    fallback_responses = [
                        "Sorry, I'm having trouble focusing right now. Could you try again?",
                        "My thoughts are a bit scattered at the moment. What was your question?",
                        "I apologize, but I'm having some technical difficulties. Can you repeat that?"
                    ]
                response_text = random.choice(fallback_responses)

            # 6. Record the interaction
            await self.relationship_manager.record_interaction(guild_id, user_id)
            return response_text

        except Exception as e:
            self.logger.error(f"Chat response generation failed completely: {e}", exc_info=True)
            error_responses = [
                "Something's definitely wrong with my brain right now. Give me a moment?",
                "I can't seem to think straight. Maybe try again in a bit?",
                "My thoughts are completely jumbled. This is embarrassing.",
            ]
            return random.choice(error_responses)

    async def summarize_conversation(self, messages: List[str]) -> str:
        """Generate a conversation summary with Tika's personality."""
        if not self.is_ready(): 
            return "My brain's not cooperating right now. Can't summarize that."
            
        if len(messages) < 3:
            return "There's barely anything here to summarize. Did you mean to ask about something else?"
            
        conversation_text = "\n".join(messages[-20:])  # Limit to prevent token issues
        
        prompt = (
            "You are Tika. You've been asked to summarize a conversation. "
            "Be characteristically reluctant but thorough. Start with something like 'Fine, if you insist...' "
            "or 'I suppose I can tell you what happened...' then provide a clear, informative summary. "
            "Keep it concise (under 200 words) and end with a slightly sassy comment about the conversation. "
            "Speak naturally - NO roleplay actions in asterisks or physical descriptions.\n\n"
            f"CONVERSATION TO SUMMARIZE:\n{conversation_text}\n\nYOUR SUMMARY:"
        )
        
        try:
            response = self.model.generate_content(prompt)
            summary = response.text.strip()
            return self._clean_response(summary)
        except Exception as e:
            self.logger.error(f"Summarization failed: {e}")
            return "I couldn't make sense of that conversation. It was probably nonsense anyway."
            
    async def generate_proactive_comment(self, messages: List[str]) -> str:
        """Generate a brief, natural interjection for ongoing conversations."""
        if not self.is_ready(): 
            return ""
            
        if len(messages) < 3:
            return ""
            
        # Limit message context to prevent token issues
        conversation_text = "\n".join(messages[-10:])
        
        prompt = (
            "You are Tika, observing a Discord conversation. Make a brief, natural comment (maximum 40 words). "
            "Don't announce yourself as a bot - just interject naturally like another person would. "
            "Speak naturally like a real person - NO roleplay actions in asterisks or physical descriptions. "
            "Only respond if you have something genuinely interesting or helpful to add. "
            "Examples of your style:\n"
            "- 'That's... actually kind of interesting.'\n"
            "- 'You know there's an easier way to do that, right?'\n"
            "- 'Um, actually... that's not quite how it works.'\n"
            "- 'Well, that escalated quickly.'\n"
            "- 'I probably shouldn't say this, but...'\n\n"
            f"RECENT CONVERSATION:\n{conversation_text}\n\n"
            "RESPOND ONLY if you have something valuable to add, otherwise return 'SKIP':\n"
            "YOUR COMMENT:"
        )
        
        try:
            response = self.model.generate_content(prompt)
            comment = response.text.strip()
            
            # Skip if AI says to skip or comment is too generic
            if comment.upper() == 'SKIP' or len(comment) < 5:
                return ""
            
            # Remove quotes if the AI added them
            if comment.startswith('"') and comment.endswith('"'):
                comment = comment[1:-1]
            
            # Clean the response
            comment = self._clean_response(comment)
            
            # Final length check
            if len(comment) > 200:  # Be conservative for proactive comments
                return ""
                
            return comment
            
        except Exception as e:
            self.logger.error(f"Proactive comment generation failed: {e}")
            return ""

    async def process_text_into_memory(self, content: str) -> Optional[str]:
        """Process learned content into Tika's memory with her personality."""
        if not self.is_ready():
            return None
            
        # Truncate very long content to prevent token issues
        if len(content) > 2000:
            content = content[:2000] + "..."
            
        prompt = (
            "You are Tika. Process this information into a concise fact (under 100 words) you can remember and reference later. "
            "Keep it informative but show your characteristic slight reluctance about learning new things. "
            "Use natural speech like 'I learned that [fact]. I suppose that's useful to know.' "
            "Speak naturally - NO roleplay actions in asterisks or physical descriptions.\n\n"
            f"CONTENT TO PROCESS:\n{content}\n\nYOUR PROCESSED MEMORY:"
        )
        
        try:
            response = self.model.generate_content(prompt)
            memory = response.text.strip()
            return self._clean_response(memory)
        except Exception as e:
            self.logger.error(f"Text processing into memory failed: {e}")
            return None