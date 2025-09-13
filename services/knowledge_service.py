# services/knowledge_service.py
import logging
from typing import Dict, List
import aiohttp
from bs4 import BeautifulSoup
import asyncio

class KnowledgeService:
    def __init__(self, data_manager, gemini_service):
        self.logger = logging.getLogger(__name__)
        self.data_manager = data_manager
        self.gemini_service = gemini_service
        self.knowledge_cache: Dict = {}

    async def on_ready(self):
        """Loads the knowledge base into memory."""
        self.knowledge_cache = await self.data_manager.get_data("knowledge_base")
        self.logger.info(f"Knowledge base loaded with {len(self.get_all_facts())} facts.")

    async def learn_from_url(self, url: str, session: aiohttp.ClientSession) -> bool:
        """Scrapes a URL, processes the content, and adds it to the knowledge base."""
        learned_urls = self.knowledge_cache.setdefault("learned_urls", [])
        if url in learned_urls:
            self.logger.info(f"Already learned from {url}.")
            return True

        try:
            async with session.get(url, timeout=20) as response:
                if response.status != 200 or 'text/html' not in response.headers.get('Content-Type', ''):
                    self.logger.warning(f"Failed to fetch valid content from {url}, status: {response.status}")
                    return False
                
                soup = BeautifulSoup(await response.text(), 'html.parser')
                for script_or_style in soup(["script", "style"]):
                    script_or_style.decompose()
                
                content = soup.get_text(separator="\n", strip=True)
                if not content:
                    self.logger.warning(f"No text content found at {url}")
                    return False

            processed_fact = await self.gemini_service.process_text_into_memory(content)
            
            if processed_fact:
                facts = self.knowledge_cache.setdefault("facts", [])
                facts.append(processed_fact)
                learned_urls.append(url)
                await self.data_manager.save_data("knowledge_base", self.knowledge_cache)
                self.logger.info(f"Successfully learned a new fact from {url}")
                return True
        except Exception as e:
            self.logger.error(f"Failed to learn from URL {url}: {e}", exc_info=True)
        return False

    def get_all_facts(self) -> List[str]:
        """Returns all learned facts to be used as context."""
        return self.knowledge_cache.get("facts", [])

    async def clear_all_facts(self):
        """Clears all learned facts from the knowledge base."""
        self.knowledge_cache = {"learned_urls": [], "facts": []}
        await self.data_manager.save_data("knowledge_base", self.knowledge_cache)
        self.logger.info("Knowledge base has been cleared.")