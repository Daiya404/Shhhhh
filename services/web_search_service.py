# services/web_search_service.py
import logging
from typing import Optional, List, Dict
import asyncio
import aiohttp
from ddgs import DDGS

class WebSearchService:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.logger = logging.getLogger(__name__)
        self._ddgs = None

    def is_ready(self) -> bool:
        return True

    async def search(self, query: str, max_results: int = 3) -> Optional[str]:
        """
        Perform a web search using DuckDuckGo with proper error handling and fallbacks.
        """
        self.logger.info(f"Performing DuckDuckGo search for: {query}")
        
        # Try multiple search methods for better reliability
        search_methods = [
            self._search_with_atext,
            self._search_with_text,
            self._fallback_search
        ]
        
        for method in search_methods:
            try:
                result = await method(query, max_results)
                if result:
                    return result
            except Exception as e:
                self.logger.warning(f"Search method {method.__name__} failed: {e}")
                continue
        
        # All methods failed
        self.logger.error(f"All search methods failed for query: {query}")
        return "I tried searching for that, but the internet seems to be having issues. Typical."

    async def _search_with_atext(self, query: str, max_results: int) -> Optional[str]:
        """Try using the async atext method (newer versions)."""
        try:
            # Run in executor to handle potential blocking
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, 
                lambda: list(DDGS().text(query, max_results=max_results))
            )
            
            if results:
                return self._format_search_results(results)
        except AttributeError:
            # Method doesn't exist in this version
            raise Exception("atext method not available")
        except Exception as e:
            raise Exception(f"atext search failed: {e}")

    async def _search_with_text(self, query: str, max_results: int) -> Optional[str]:
        """Try using the synchronous text method (most common)."""
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, 
                lambda: list(DDGS().text(query, max_results=max_results))
            )
            
            if results:
                return self._format_search_results(results)
        except Exception as e:
            raise Exception(f"text search failed: {e}")

    async def _fallback_search(self, query: str, max_results: int) -> Optional[str]:
        """Fallback search using basic HTTP requests if DDGS fails completely."""
        try:
            # Simple fallback - could implement a basic web scraping search here
            # For now, return a graceful failure message
            raise Exception("Fallback search not implemented")
        except Exception as e:
            raise Exception(f"Fallback search failed: {e}")

    def _format_search_results(self, results: List[Dict]) -> str:
        """Format search results with Tika's personality and length limits."""
        if not results:
            return "I searched everywhere and found nothing. Maybe try asking something that actually exists?"
        
        formatted_results = []
        total_length = 0
        
        for i, item in enumerate(results):
            # Handle different possible key names
            title = item.get('title') or item.get('t') or f"Result {i+1}"
            body = item.get('body') or item.get('snippet') or item.get('s') or "No description available."
            url = item.get('href') or item.get('url') or ""
            
            # Truncate long descriptions
            if len(body) > 200:
                body = body[:197] + "..."
            
            # Format with Tika's personality
            result_text = f"**{title}**\n{body}"
            if url:
                result_text += f"\n<{url}>"
            
            # Check length limits (leave room for Tika's commentary)
            if total_length + len(result_text) > 3500:  # Conservative limit
                break
                
            formatted_results.append(result_text)
            total_length += len(result_text)
        
        # Add Tika's commentary
        search_response = "\n\n".join(formatted_results)
        
        # Add a personality-appropriate intro
        intros = [
            "Fine, here's what I found:",
            "I suppose this might help:",
            "Here's what the internet had to say:",
            "I found some things. Whether they're useful is another question:",
        ]
        
        import random
        intro = random.choice(intros)
        final_response = f"{intro}\n\n{search_response}"
        
        # Final length check
        if len(final_response) > 3900:
            final_response = final_response[:3900] + "\n\n...and that's all you're getting."
        
        return final_response

    async def quick_fact_search(self, query: str) -> Optional[str]:
        """
        Perform a quick search for factual information, returning just the most relevant snippet.
        """
        try:
            full_result = await self.search(query, max_results=1)
            if full_result and "here's what i found:" in full_result.lower():
                # Extract just the first result without Tika's commentary for AI processing
                lines = full_result.split('\n')
                relevant_lines = []
                for line in lines[2:]:  # Skip intro lines
                    if line.strip() and not line.startswith('<'):
                        relevant_lines.append(line)
                    if len(relevant_lines) >= 3:  # Get title and description
                        break
                return '\n'.join(relevant_lines)
        except Exception as e:
            self.logger.error(f"Quick fact search failed: {e}")
        
        return None