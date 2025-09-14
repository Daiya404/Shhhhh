# services/web_search_service.py
import logging
from typing import Optional
from ddgs import DDGS # Import from the new ddgs library

class WebSearchService:
    def __init__(self, session):
        # The session is not used by this library, but we keep it for consistency
        self.logger = logging.getLogger(__name__)

    def is_ready(self) -> bool:
        return True

    async def search(self, query: str) -> Optional[str]:
        self.logger.info(f"Performing DuckDuckGo search for: {query}")
        try:
            # --- THIS IS THE FIX ---
            # The new syntax is simpler. We instantiate DDGS and then await the async method.
            results = await DDGS().atext(query, max_results=3)
            
            if not results:
                return "I searched the web and found absolutely nothing useful. Your query was probably terrible."
            
            formatted_results = [f"Title: {item.get('title', 'N/A')}\nSnippet: {item.get('body', 'N/A')}" for item in results]
            return "\n\n".join(formatted_results)
            
        except Exception as e:
            self.logger.error(f"An error occurred during DuckDuckGo search: {e}", exc_info=True)
            return "Something went wrong while I was searching. How tedious."