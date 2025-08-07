import discord
from discord.ext import commands
import logging
import aiohttp
from typing import Optional, Dict, List

# This cog is special. It doesn't have user commands.
# It acts as a centralized service for other cogs to use.

class AniListAPI(commands.Cog, name="AniListAPI"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # Create a single, persistent session for all API calls for efficiency
        self.session = aiohttp.ClientSession()
        self.api_url = "https://graphql.anilist.co"

    async def cog_unload(self):
        """Ensure the session is closed when the bot shuts down."""
        await self.session.close()

    async def _make_request(self, query: str, variables: dict) -> Optional[Dict]:
        """A single, robust function to handle all AniList API requests."""
        try:
            async with self.session.post(self.api_url, json={'query': query, 'variables': variables}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data")
                else:
                    self.logger.error(f"AniList API returned status {resp.status}: {await resp.text()}")
                    return None
        except aiohttp.ClientError as e:
            self.logger.error(f"AIOHTTP error during AniList request: {e}", exc_info=True)
            return None
        except Exception as e:
            self.logger.error(f"An unexpected error occurred during AniList request: {e}", exc_info=True)
            return None

    # Public Functions

    async def search_character(self, character_name: str) -> Optional[Dict]:
        """
        Searches for a single character on AniList.
        Used by: The Word Game.
        Returns: A dictionary of character data if found, otherwise None.
        """
        query = """
        query ($search: String) {
            Character(search: $search) {
                id
                name {
                    full
                    native
                }
                image {
                    large
                }
                media(sort: POPULARITY_DESC, perPage: 1) {
                    nodes {
                        title {
                            romaji
                            english
                        }
                    }
                }
            }
        }
        """
        variables = {"search": character_name}
        data = await self._make_request(query, variables)
        return data.get("Character") if data else None

    async def search_media(self, search_term: str, media_type: str) -> Optional[List[Dict]]:
        """
        Searches for a list of anime, manga, or light novels.
        Used by: The /search command.
        Returns: A list of media dictionaries if found, otherwise None.
        """
        query = """
        query ($search: String, $type: MediaType) {
            Page(page: 1, perPage: 5) {
                media(search: $search, type: $type, sort: SEARCH_MATCH) {
                    id
                    title {
                        romaji
                        english
                        native
                    }
                    format
                    status
                    description(asHtml: false)
                    averageScore
                    coverImage {
                        extraLarge
                    }
                    siteUrl
                }
            }
        }
        """
        variables = {"search": search_term, "type": media_type} # media_type will be "ANIME" or "MANGA"
        data = await self._make_request(query, variables)
        return data.get("Page", {}).get("media") if data else None

    async def get_airing_schedule(self, page: int = 1) -> Optional[Dict]:
        """
        Gets the airing schedule for today.
        Used by: The /anime schedule command.
        Returns: A dictionary containing a list of airing media and page info.
        """
        query = """
        query ($page: Int) {
            Page(page: $page, perPage: 10) {
                pageInfo {
                    hasNextPage
                }
                airingSchedules(notYetAired: false, sort: TIME_DESC) {
                    airingAt
                    episode
                    media {
                        id
                        title {
                            romaji
                            english
                        }
                        siteUrl
                    }
                }
            }
        }
        """
        variables = {"page": page}
        return await self._make_request(query, variables)
        
    async def get_media_release(self, search_term: str) -> Optional[Dict]:
        """
        Gets detailed release/airing information for a single anime.
        Used by: The /anime release command.
        Returns: A dictionary of a single media's data if found, otherwise None.
        """
        query = """
        query ($search: String) {
            Media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
                id
                title {
                    romaji
                    english
                }
                status
                nextAiringEpisode {
                    airingAt
                    episode
                }
                startDate {
                    year
                    month
                    day
                }
                siteUrl
            }
        }
        """
        variables = {"search": search_term}
        data = await self._make_request(query, variables)
        return data.get("Media") if data else None

async def setup(bot):
    await bot.add_cog(AniListAPI(bot))