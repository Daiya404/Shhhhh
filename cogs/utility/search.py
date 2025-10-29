# cogs/utility/search.py

import discord
from discord.ext import commands
from ddgs import DDGS
from urllib.parse import urlparse
import asyncio
from datetime import datetime, timedelta

class SearchView(discord.ui.View):
    def __init__(self, cog, query: str, all_results: list, shown_indices: set, author_id: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog
        self.query = query
        self.all_results = all_results
        self.shown_indices = shown_indices
        self.current_page = 0
        self.results_per_page = 3
        self.author_id = author_id
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your search! Run your own.", ephemeral=True)
            return False
        return True
    
    def get_page_results(self):
        start = self.current_page * self.results_per_page
        end = start + self.results_per_page
        return self.all_results[start:end]
    
    def create_embed(self):
        embed = discord.Embed(
            title="🔍 Search Results",
            color=0x2F3136
        )
        
        page_results = self.get_page_results()
        description_parts = []
        
        for result in page_results:
            title = result.get('title', 'No Title')
            url = result.get('href', '')
            body = result.get('body', 'No description available.')
            
            try:
                domain = urlparse(url).netloc.replace('www.', '')
            except:
                domain = url
            
            body = ' '.join(body.split())
            if len(body) > 200:
                body = body[:197] + "..."
            
            result_text = f"**{title}**\n[{domain}]({url})\n{body}\n"
            description_parts.append(result_text)
        
        embed.description = "\n".join(description_parts)
        
        total_pages = (len(self.all_results) + self.results_per_page - 1) // self.results_per_page
        embed.set_footer(text=f"Page {self.current_page + 1}/{total_pages} • Powered by DuckDuckGo")
        embed.timestamp = discord.utils.utcnow()
        
        return embed
    
    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray, emoji="◀️")
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.send_message("You're already on the first page.", ephemeral=True)
    
    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray, emoji="▶️")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        total_pages = (len(self.all_results) + self.results_per_page - 1) // self.results_per_page
        if self.current_page < total_pages - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.send_message("You're already on the last page.", ephemeral=True)
    
    @discord.ui.button(label="Other Results", style=discord.ButtonStyle.blurple, emoji="🔄")
    async def other_results_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        try:
            # Perform search in thread to avoid blocking
            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.text(
                        query=self.query,
                        region='wt-wt',
                        safesearch='off',
                        max_results=20
                    ))
            
            new_results = await asyncio.to_thread(_search)
            
            # Filter out already shown results
            filtered_results = []
            for result in new_results:
                url = result.get('href', '')
                result_id = hash(url)
                if result_id not in self.shown_indices:
                    filtered_results.append(result)
                    self.shown_indices.add(result_id)
            
            if filtered_results:
                self.all_results = filtered_results
                self.current_page = 0
                await interaction.followup.edit_message(
                    message_id=interaction.message.id,
                    embed=self.create_embed(),
                    view=self
                )
            else:
                await interaction.followup.send("No new results found.", ephemeral=True)
                
        except Exception as e:
            self.cog.bot.logger.error(f"Error fetching other results: {e}")
            await interaction.followup.send("Failed to fetch new results.", ephemeral=True)
    
    @discord.ui.button(label="Close", style=discord.ButtonStyle.red, emoji="✖️")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Delete the search results message
        await interaction.message.delete()
        
        # Delete the original search request message if it still exists
        if interaction.message.reference and interaction.message.reference.message_id:
            try:
                original_msg = await interaction.channel.fetch_message(interaction.message.reference.message_id)
                await original_msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass  # Message already deleted or can't be deleted
        
        self.stop()

class Search(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.search_cache = {}  # Simple cache: {query: (results, timestamp)}
        self.cache_duration = timedelta(minutes=10)

    async def _is_feature_enabled(self, guild_id: int) -> bool:
        """A local check to see if the web_search feature is enabled."""
        feature_manager = self.bot.get_cog("FeatureManager")
        feature_name = "web_search" 
        
        return feature_manager and feature_manager.is_feature_enabled(guild_id, feature_name)
    
    def get_cached_results(self, query: str):
        """Get cached results if they exist and aren't expired."""
        if query in self.search_cache:
            results, timestamp = self.search_cache[query]
            if datetime.now() - timestamp < self.cache_duration:
                return results
            else:
                del self.search_cache[query]
        return None
    
    def cache_results(self, query: str, results: list):
        """Cache search results."""
        self.search_cache[query] = (results, datetime.now())
        
        # Clean old cache entries if cache gets too large
        if len(self.search_cache) > 100:
            oldest = min(self.search_cache.items(), key=lambda x: x[1][1])
            del self.search_cache[oldest[0]]
    
    async def perform_search(self, query: str, max_results: int = 10):
        """Perform a web search with caching."""
        # Check cache first
        cached = self.get_cached_results(query)
        if cached:
            return cached
        
        # Perform new search in thread to avoid blocking
        def _search():
            with DDGS() as ddgs:
                return list(ddgs.text(
                    query=query,
                    region='wt-wt',
                    safesearch='off',
                    max_results=max_results
                ))
        
        results = await asyncio.to_thread(_search)
        
        # Cache results
        self.cache_results(query, results)
        return results
    
    async def handle_quick_action(self, message: discord.Message, action: str, query: str):
        """Handle quick action commands like define, weather, wiki, etc."""
        try:
            if action == "define":
                return await self.quick_define(message, query)
            elif action == "weather":
                return await self.quick_weather(message, query)
            elif action == "wiki":
                return await self.quick_wiki(message, query)
            elif action == "calc" or action == "calculate":
                return await self.quick_calc(message, query)
            elif action == "time":
                return await self.quick_time(message, query)
            elif action == "translate":
                return await self.quick_translate(message, query)
        except Exception as e:
            self.bot.logger.error(f"Quick action error ({action}): {e}")
            return False
        return False
    
    async def quick_define(self, message: discord.Message, word: str):
        """Get definition of a word."""
        search_results = await self.perform_search(f"define {word}", max_results=3)
        
        if not search_results:
            return False
        
        embed = discord.Embed(
            title=f"📚 Definition: {word.title()}",
            color=0x5865F2
        )
        
        # Get the most relevant result (usually dictionary sites)
        for result in search_results:
            title = result.get('title', '')
            if 'definition' in title.lower() or 'meaning' in title.lower():
                body = result.get('body', 'No definition found.')
                url = result.get('href', '')
                
                body = ' '.join(body.split())
                if len(body) > 300:
                    body = body[:297] + "..."
                
                embed.description = body
                embed.add_field(name="Source", value=f"[Read more]({url})", inline=False)
                break
        
        if not embed.description:
            embed.description = search_results[0].get('body', 'No definition found.')
        
        embed.set_footer(text="Powered by DuckDuckGo")
        embed.timestamp = discord.utils.utcnow()
        
        await message.reply(embed=embed, mention_author=False)
        return True
    
    async def quick_weather(self, message: discord.Message, location: str):
        """Get weather for a location."""
        search_results = await self.perform_search(f"weather {location}", max_results=3)
        
        if not search_results:
            return False
        
        embed = discord.Embed(
            title=f"🌤️ Weather: {location.title()}",
            color=0x3498db
        )
        
        # Get weather info from results
        for result in search_results:
            body = result.get('body', '')
            if any(word in body.lower() for word in ['temperature', 'forecast', 'weather', '°']):
                url = result.get('href', '')
                
                body = ' '.join(body.split())
                if len(body) > 300:
                    body = body[:297] + "..."
                
                embed.description = body
                embed.add_field(name="Full Forecast", value=f"[View details]({url})", inline=False)
                break
        
        if not embed.description:
            embed.description = search_results[0].get('body', 'Weather information not available.')
        
        embed.set_footer(text="Powered by DuckDuckGo")
        embed.timestamp = discord.utils.utcnow()
        
        await message.reply(embed=embed, mention_author=False)
        return True
    
    async def quick_wiki(self, message: discord.Message, topic: str):
        """Get Wikipedia summary."""
        search_results = await self.perform_search(f"{topic} wikipedia", max_results=5)
        
        if not search_results:
            return False
        
        # Find Wikipedia result
        wiki_result = None
        for result in search_results:
            url = result.get('href', '')
            if 'wikipedia.org' in url:
                wiki_result = result
                break
        
        if not wiki_result:
            return False
        
        embed = discord.Embed(
            title=f"📖 {wiki_result.get('title', topic)}",
            color=0x000000
        )
        
        body = wiki_result.get('body', 'No summary available.')
        body = ' '.join(body.split())
        if len(body) > 400:
            body = body[:397] + "..."
        
        embed.description = body
        embed.add_field(
            name="Read Full Article", 
            value=f"[Wikipedia]({wiki_result.get('href', '')})", 
            inline=False
        )
        embed.set_footer(text="Source: Wikipedia")
        embed.timestamp = discord.utils.utcnow()
        
        await message.reply(embed=embed, mention_author=False)
        return True
    
    async def quick_calc(self, message: discord.Message, expression: str):
        """Quick calculation."""
        search_results = await self.perform_search(f"calculate {expression}", max_results=3)
        
        if not search_results:
            return False
        
        embed = discord.Embed(
            title=f"🔢 Calculator",
            color=0xe74c3c
        )
        
        # Look for calculation results
        for result in search_results:
            body = result.get('body', '')
            if any(char in body for char in ['=', '≈']):
                body = ' '.join(body.split())
                embed.description = f"**{expression}**\n{body[:200]}"
                break
        
        if not embed.description:
            embed.description = f"**{expression}**\n{search_results[0].get('body', '')[:200]}"
        
        embed.set_footer(text="Powered by DuckDuckGo")
        
        await message.reply(embed=embed, mention_author=False)
        return True
    
    async def quick_time(self, message: discord.Message, location: str):
        """Get current time in a location."""
        search_results = await self.perform_search(f"current time in {location}", max_results=3)
        
        if not search_results:
            return False
        
        embed = discord.Embed(
            title=f"🕐 Time in {location.title()}",
            color=0x9b59b6
        )
        
        for result in search_results:
            body = result.get('body', '')
            if any(word in body.lower() for word in ['time', 'clock', ':']):
                body = ' '.join(body.split())
                embed.description = body[:200]
                break
        
        if not embed.description:
            embed.description = search_results[0].get('body', 'Time information not available.')
        
        embed.set_footer(text="Powered by DuckDuckGo")
        embed.timestamp = discord.utils.utcnow()
        
        await message.reply(embed=embed, mention_author=False)
        return True
    
    async def quick_translate(self, message: discord.Message, text: str):
        """Quick translation (searches for translation)."""
        search_results = await self.perform_search(f"translate {text}", max_results=3)
        
        if not search_results:
            return False
        
        embed = discord.Embed(
            title=f"🌐 Translation",
            color=0x1abc9c
        )
        
        for result in search_results:
            url = result.get('href', '')
            if 'translate' in url:
                body = result.get('body', '')
                body = ' '.join(body.split())
                embed.description = body[:300]
                embed.add_field(name="Translator", value=f"[Open Translator]({url})", inline=False)
                break
        
        if not embed.description:
            embed.description = search_results[0].get('body', 'Translation not available.')
        
        embed.set_footer(text="Powered by DuckDuckGo")
        
        await message.reply(embed=embed, mention_author=False)
        return True

    @commands.Cog.listener("on_message")
    async def on_message_search(self, message: discord.Message):
        """Listens for messages to trigger a web search."""
        if message.author.bot or not message.guild:
            return
        
        if not await self._is_feature_enabled(message.guild.id):
            return
            
        if not message.content.startswith(self.bot.user.mention):
            return

        content = message.content.replace(self.bot.user.mention, '', 1).strip()
        parts = content.split(maxsplit=1)
        
        if not parts or parts[0].lower() != 'search':
            return
        
        if len(parts) < 2:
            await message.reply(
                "Hmph. If you want me to search for something, you have to actually tell me what it is.",
                mention_author=False
            )
            return
        
        query_full = parts[1]
        
        # Check for quick actions
        quick_actions = {
            'define': ['define', 'definition', 'meaning'],
            'weather': ['weather', 'forecast'],
            'wiki': ['wiki', 'wikipedia'],
            'calc': ['calc', 'calculate', 'math'],
            'time': ['time', 'clock']
        }
        
        # Check if query starts with a quick action
        query_lower = query_full.lower()
        for action, keywords in quick_actions.items():
            for keyword in keywords:
                if query_lower.startswith(keyword + ' '):
                    query_content = query_full[len(keyword):].strip()
                    async with message.channel.typing():
                        handled = await self.handle_quick_action(message, action, query_content)
                        if handled:
                            return
                    break

        # Regular search
        query = query_full

        try:
            # Send initial "searching" message
            search_msg = await message.reply(
                f"🔎 Searching for **{query}**...",
                mention_author=False
            )
            
            async with message.channel.typing():
                search_results = await self.perform_search(query, max_results=15)

                if not search_results:
                    await search_msg.edit(content=f"I couldn't find anything for `{query}`. Try being less obscure.")
                    return

                # Track shown result indices
                shown_indices = {hash(r.get('href', '')) for r in search_results[:3]}
                
                # Create view with pagination
                view = SearchView(
                    cog=self,
                    query=query,
                    all_results=search_results,
                    shown_indices=shown_indices,
                    author_id=message.author.id
                )
                
                embed = view.create_embed()
                await search_msg.edit(content=None, embed=embed, view=view)

        except Exception as e:
            self.bot.logger.error(f"Error during DDGS search for query '{query}': {e}")
            await message.reply(
                "Something went wrong with the search. It's probably a 'you' problem.",
                mention_author=False
            )

async def setup(bot):
    await bot.add_cog(Search(bot))