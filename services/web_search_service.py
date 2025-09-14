# services/web_search_service.py
import logging
from typing import Optional, List, Dict
from ddgs import DDGS # Import from the correct ddgs library

class WebSearchService:
    def __init__(self, session):
        # The session is not used by this library, but we keep it for consistency.
        self.logger = logging.getLogger(__name__)

    def is_ready(self) -> bool:
        return True

    async def search(self, query: str) -> Optional[str]:
        self.logger.info(f"Performing DuckDuckGo search for: {query}")
        try:
            # --- THIS IS THE FIX ---
            # 1. Use `DDGS().atext()` which is the correct ASYNC method.
            # 2. `atext` returns an async generator, so we use a list comprehension to gather the results.
            results: List[Dict] = [r async for r in DDGS().atext(query, max_results=3)]
            
            if not results:
                return "I searched the web and found absolutely nothing useful. Your query was probably terrible."
            
            # The keys in the dictionary are 'title' and 'body'.
            formatted_results = [f"Title: {item.get('title', 'N/A')}\nSnippet: {item.get('body', 'N/A')}" for item in results]
            return "\n\n".join(formatted_results)
            
        except Exception as e:
            self.logger.error(f"An error occurred during DuckDuckGo search: {e}", exc_info=True)
            return "Something went wrong while I was searching. How tedious."