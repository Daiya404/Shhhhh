import discord
from discord.ext import commands
import aiohttp
import asyncio
import json
import time
import os
import random
from typing import Dict, List, Optional, Tuple
import re
import unicodedata

class AnimeNameGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game_channels: Dict[int, dict] = {}  # guild_id -> game_data
        self.used_names: Dict[int, set] = {}  # guild_id -> set of used names
        self.user_scores: Dict[int, Dict[int, int]] = {}  # guild_id -> {user_id: xp}
        self.current_letters: Dict[int, dict] = {}  # guild_id -> {letter, timestamp, message_id}
        
        # Letter frequency weights (higher = more likely to appear)
        self.letter_weights = {
            'a': 25, 'b': 15, 'c': 18, 'd': 12, 'e': 20, 'f': 10, 'g': 12, 'h': 15,
            'i': 22, 'j': 8, 'k': 18, 'l': 12, 'm': 20, 'n': 15, 'o': 18, 'p': 10,
            'q': 5, 'r': 16, 's': 25, 't': 20, 'u': 15, 'v': 8, 'w': 10, 'x': 3,
            'y': 8, 'z': 6
        }
        
        self.load_data()
        
    def cog_unload(self):
        """Save data when cog is unloaded"""
        self.save_data()

    def load_data(self):
        """Load game data from environment variables or file"""
        try:
            # Try to load from environment variable first (for Railway/Heroku)
            data_str = os.getenv('ANIME_GAME_DATA')
            if data_str:
                data = json.loads(data_str)
            else:
                # Fallback to file for local development
                try:
                    with open('anime_game_data.json', 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except FileNotFoundError:
                    data = {}
            
            # Convert string keys back to integers for guild/user IDs
            self.game_channels = {int(k): v for k, v in data.get('game_channels', {}).items()}
            self.used_names = {int(k): set(v) for k, v in data.get('used_names', {}).items()}
            self.user_scores = {
                int(guild_id): {int(user_id): score for user_id, score in users.items()}
                for guild_id, users in data.get('user_scores', {}).items()
            }
            self.current_letters = {int(k): v for k, v in data.get('current_letters', {}).items()}
            
        except Exception as e:
            self.bot.logger.error(f"Error loading anime game data: {e}")

    def save_data(self):
        """Save game data to environment variable or file"""
        try:
            data = {
                'game_channels': {str(k): v for k, v in self.game_channels.items()},
                'used_names': {str(k): list(v) for k, v in self.used_names.items()},
                'user_scores': {
                    str(guild_id): {str(user_id): score for user_id, score in users.items()}
                    for guild_id, users in self.user_scores.items()
                },
                'current_letters': {str(k): v for k, v in self.current_letters.items()}
            }
            
            data_str = json.dumps(data, ensure_ascii=False)
            
            # Save to environment variable for Railway/Heroku
            os.environ['ANIME_GAME_DATA'] = data_str
            
            # Also save to file for local development
            try:
                with open('anime_game_data.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except:
                pass  # Don't fail if file can't be written (read-only filesystem)
                
        except Exception as e:
            self.bot.logger.error(f"Error saving anime game data: {e}")

    def normalize_name(self, name: str) -> str:
        """Normalize character name for comparison"""
        # Remove extra spaces and convert to lowercase
        name = ' '.join(name.strip().split()).lower()
        
        # Remove common prefixes/suffixes and normalize
        name = unicodedata.normalize('NFKD', name)
        
        return name

    def get_first_letter(self, name: str) -> str:
        """Get the first meaningful letter from a name"""
        # Remove spaces and punctuation, get first alphabetic character
        clean_name = re.sub(r'[^\w]', '', name.lower())
        
        for char in clean_name:
            if char.isalpha():
                return char
        
        return clean_name[0] if clean_name else ''

    def get_random_letter(self) -> str:
        """Get a random letter based on weights"""
        letters = list(self.letter_weights.keys())
        weights = list(self.letter_weights.values())
        return random.choices(letters, weights=weights)[0]

    async def search_anilist_character(self, name: str) -> Optional[dict]:
        """Search for character on AniList API"""
        query = '''
        query ($search: String) {
            Character(search: $search) {
                id
                name {
                    full
                    native
                    alternative
                }
                media {
                    nodes {
                        title {
                            romaji
                            english
                        }
                        type
                    }
                }
            }
        }
        '''
        
        variables = {'search': name}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://graphql.anilist.co',
                    json={'query': query, 'variables': variables},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('data', {}).get('Character')
                    else:
                        return None
        except Exception as e:
            self.bot.logger.error(f"AniList API error: {e}")
            return None

    def calculate_xp(self, time_taken: float) -> int:
        """Calculate XP based on response time"""
        if time_taken <= 10:
            return 3000
        elif time_taken <= 20:
            return 2000
        elif time_taken <= 30:
            return 1500
        elif time_taken <= 60:  # 1 minute
            return 1000
        elif time_taken <= 300:  # 5 minutes
            return 500
        elif time_taken <= 1800:  # 30 minutes
            return 200
        else:
            return 50

    async def send_new_letter(self, channel, guild_id: int):
        """Send a new random letter challenge"""
        letter = self.get_random_letter()
        current_time = time.time()
        
        embed = discord.Embed(
            title="🎯 New Letter Challenge!",
            description=f"Name an anime character that starts with **{letter.upper()}**!",
            color=0x00aaff
        )
        embed.add_field(
            name="XP Rewards",
            value="• Under 10s: 3000 XP\n"
                  "• Under 20s: 2000 XP\n"
                  "• Under 30s: 1500 XP\n"
                  "• Under 1min: 1000 XP\n"
                  "• Under 5min: 500 XP\n"
                  "• Under 30min: 200 XP\n"
                  "• Over 30min: 50 XP",
            inline=False
        )
        embed.set_footer(text="First valid character wins!")
        
        message = await channel.send(embed=embed)
        
        # Store current letter challenge
        self.current_letters[guild_id] = {
            'letter': letter,
            'timestamp': current_time,
            'message_id': message.id,
            'active': True
        }
        
        self.save_data()

    @discord.app_commands.command(name='animegame', description='Show anime name game info and commands')
    async def anime_game_info(self, interaction: discord.Interaction):
        """Show anime name game information"""
        embed = discord.Embed(
            title="🎌 Anime Name Game (Random Letter Mode)",
            description="Play the anime character name game with random letters!",
            color=0x00ff00
        )
        embed.add_field(
            name="How to Play",
            value="• Random letters will be posted in the game channel\n"
                  "• Be the first to name a valid anime character starting with that letter\n"
                  "• Each character name can only be used once per server\n"
                  "• Faster responses = more XP!",
            inline=False
        )
        embed.add_field(
            name="XP System",
            value="• Under 10s: 3000 XP\n"
                  "• Under 20s: 2000 XP\n"
                  "• Under 30s: 1500 XP\n"
                  "• Under 1min: 1000 XP\n"
                  "• Under 5min: 500 XP\n"
                  "• Under 30min: 200 XP\n"
                  "• Over 30min: 50 XP",
            inline=False
        )
        embed.add_field(
            name="Slash Commands",
            value="`/setchannel` - Set game channel\n"
                  "`/newletter` - Generate new letter (if no active challenge)\n"
                  "`/leaderboard` - View XP leaderboard\n"
                  "`/stats` - View your stats\n"
                  "`/resetgame` - Reset game (Admin only)",
            inline=False
        )
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name='setchannel', description='Set the anime name game channel')
    @discord.app_commands.describe(channel='The channel to set as game channel (current channel if not specified)')
    @discord.app_commands.default_permissions(manage_channels=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        """Set the anime name game channel"""
        if channel is None:
            channel = interaction.channel
        
        guild_id = interaction.guild.id
        
        # Initialize guild data if not exists
        if guild_id not in self.game_channels:
            self.game_channels[guild_id] = {}
            self.used_names[guild_id] = set()
            self.user_scores[guild_id] = {}
            self.current_letters[guild_id] = {}
        
        self.game_channels[guild_id]['channel_id'] = channel.id
        self.save_data()
        
        embed = discord.Embed(
            title="✅ Game Channel Set",
            description=f"Anime name game is now active in {channel.mention}!",
            color=0x00ff00
        )
        embed.add_field(
            name="Rules",
            value="• Random letters will be posted automatically\n"
                  "• Be first to name a character starting with that letter\n"
                  "• No repeated character names\n"
                  "• Verified through AniList database",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)
        
        # Send first letter challenge
        await self.send_new_letter(channel, guild_id)

    @discord.app_commands.command(name='newletter', description='Generate a new letter challenge')
    async def new_letter(self, interaction: discord.Interaction):
        """Generate a new letter challenge"""
        guild_id = interaction.guild.id
        
        # Check if game is set up
        if guild_id not in self.game_channels:
            await interaction.response.send_message("❌ Game channel not set! Use `/setchannel` first.")
            return
        
        # Check if there's an active challenge
        if (guild_id in self.current_letters and 
            self.current_letters[guild_id].get('active', False)):
            current_letter = self.current_letters[guild_id]['letter']
            await interaction.response.send_message(
                f"❌ There's already an active challenge for letter **{current_letter.upper()}**!"
            )
            return
        
        channel_id = self.game_channels[guild_id]['channel_id']
        channel = self.bot.get_channel(channel_id)
        
        if not channel:
            await interaction.response.send_message("❌ Game channel not found!")
            return
        
        await interaction.response.send_message("🎯 Generating new letter challenge...")
        await self.send_new_letter(channel, guild_id)

    @discord.app_commands.command(name='leaderboard', description='Show anime game XP leaderboard')
    @discord.app_commands.describe(page='Page number to view')
    async def leaderboard(self, interaction: discord.Interaction, page: int = 1):
        """Show XP leaderboard"""
        guild_id = interaction.guild.id
        
        if guild_id not in self.user_scores or not self.user_scores[guild_id]:
            await interaction.response.send_message("📊 No scores recorded yet! Start playing to see the leaderboard.")
            return
        
        # Sort users by XP
        sorted_users = sorted(
            self.user_scores[guild_id].items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Pagination
        per_page = 10
        total_pages = (len(sorted_users) + per_page - 1) // per_page
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_users = sorted_users[start_idx:end_idx]
        
        embed = discord.Embed(
            title="🏆 Anime Name Game Leaderboard",
            color=0xffd700
        )
        
        leaderboard_text = ""
        for i, (user_id, xp) in enumerate(page_users, start=start_idx + 1):
            user = self.bot.get_user(user_id)
            username = user.display_name if user else f"Unknown User ({user_id})"
            
            # Add medal emojis for top 3
            medal = ""
            if i == 1:
                medal = "🥇 "
            elif i == 2:
                medal = "🥈 "
            elif i == 3:
                medal = "🥉 "
            
            leaderboard_text += f"{medal}**{i}.** {username} - {xp:,} XP\n"
        
        embed.description = leaderboard_text
        embed.set_footer(text=f"Page {page}/{total_pages} • Total Players: {len(sorted_users)}")
        
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name='stats', description='Show anime game stats for a user')
    @discord.app_commands.describe(user='User to check stats for (yourself if not specified)')
    async def stats(self, interaction: discord.Interaction, user: discord.Member = None):
        """Show user stats"""
        if user is None:
            user = interaction.user
        
        guild_id = interaction.guild.id
        user_id = user.id
        
        if guild_id not in self.user_scores or user_id not in self.user_scores[guild_id]:
            await interaction.response.send_message(f"📊 {user.display_name} hasn't played the anime name game yet!")
            return
        
        xp = self.user_scores[guild_id][user_id]
        
        # Find user's rank
        sorted_users = sorted(
            self.user_scores[guild_id].items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        rank = next((i + 1 for i, (uid, _) in enumerate(sorted_users) if uid == user_id), 0)
        
        embed = discord.Embed(
            title=f"📊 {user.display_name}'s Stats",
            color=0x00ff00
        )
        embed.add_field(name="XP", value=f"{xp:,}", inline=True)
        embed.add_field(name="Rank", value=f"#{rank}", inline=True)
        embed.add_field(name="Total Players", value=f"{len(sorted_users)}", inline=True)
        
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name='resetgame', description='Reset the anime name game (Admin only)')
    @discord.app_commands.default_permissions(administrator=True)
    async def reset_game(self, interaction: discord.Interaction):
        """Reset the anime name game (Admin only)"""
        guild_id = interaction.guild.id
        
        # Confirmation
        embed = discord.Embed(
            title="⚠️ Reset Confirmation",
            description="This will reset all game data including:\n"
                       "• All used character names\n"
                       "• All player XP and scores\n"
                       "• Current letter challenge\n\n"
                       "This action cannot be undone!",
            color=0xff0000
        )
        
        view = ConfirmView()
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()
        
        await view.wait()
        
        if view.confirmed:
            # Reset all data for this guild
            if guild_id in self.used_names:
                self.used_names[guild_id].clear()
            if guild_id in self.user_scores:
                self.user_scores[guild_id].clear()
            if guild_id in self.current_letters:
                self.current_letters[guild_id].clear()
            
            self.save_data()
            
            embed = discord.Embed(
                title="✅ Game Reset",
                description="Anime name game has been reset successfully!",
                color=0x00ff00
            )
            await message.edit(embed=embed, view=None)
            
            # Send new letter challenge
            if guild_id in self.game_channels:
                channel_id = self.game_channels[guild_id]['channel_id']
                channel = self.bot.get_channel(channel_id)
                if channel:
                    await self.send_new_letter(channel, guild_id)
        else:
            embed = discord.Embed(
                title="❌ Reset Cancelled",
                description="Game reset has been cancelled.",
                color=0xff0000
            )
            await message.edit(embed=embed, view=None)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle messages in game channels"""
        if message.author.bot:
            return
        
        guild_id = message.guild.id
        channel_id = message.channel.id
        
        # Check if this is a game channel
        if (guild_id not in self.game_channels or 
            self.game_channels[guild_id].get('channel_id') != channel_id):
            return
        
        # Initialize guild data if needed
        if guild_id not in self.used_names:
            self.used_names[guild_id] = set()
        if guild_id not in self.user_scores:
            self.user_scores[guild_id] = {}
        if guild_id not in self.current_letters:
            self.current_letters[guild_id] = {}
        
        character_name = message.content.strip()
        
        # Skip if empty or command
        if not character_name or character_name.startswith(('/', '!!')):
            return
        
        # Check if there's an active letter challenge
        if not self.current_letters[guild_id].get('active', False):
            return
        
        required_letter = self.current_letters[guild_id]['letter']
        challenge_timestamp = self.current_letters[guild_id]['timestamp']
        
        # Check if name was already used
        normalized_name = self.normalize_name(character_name)
        if normalized_name in self.used_names[guild_id]:
            embed = discord.Embed(
                title="❌ Name Already Used",
                description=f"The name **{character_name}** has already been used!",
                color=0xff0000
            )
            await message.reply(embed=embed, delete_after=10)
            await message.delete(delay=2)
            return
        
        # Check if starts with correct letter
        first_letter = self.get_first_letter(character_name)
        if first_letter != required_letter:
            embed = discord.Embed(
                title="❌ Wrong Starting Letter",
                description=f"The name must start with **{required_letter.upper()}**\n"
                           f"Your name starts with **{first_letter.upper()}**",
                color=0xff0000
            )
            await message.reply(embed=embed, delete_after=10)
            await message.delete(delay=2)
            return
        
        # Verify character exists on AniList
        async with message.channel.typing():
            character_data = await self.search_anilist_character(character_name)
        
        if not character_data:
            embed = discord.Embed(
                title="❌ Character Not Found",
                description=f"**{character_name}** was not found in the AniList database.\n"
                           "Please use a valid anime character name.",
                color=0xff0000
            )
            await message.reply(embed=embed, delete_after=15)
            await message.delete(delay=2)
            return
        
        # Calculate XP based on response time
        current_time = time.time()
        time_taken = current_time - challenge_timestamp
        xp_gained = self.calculate_xp(time_taken)
        
        # Add to used names and update scores
        self.used_names[guild_id].add(normalized_name)
        
        user_id = message.author.id
        if user_id not in self.user_scores[guild_id]:
            self.user_scores[guild_id][user_id] = 0
        self.user_scores[guild_id][user_id] += xp_gained
        
        # Deactivate current challenge
        self.current_letters[guild_id]['active'] = False
        
        # Save data
        self.save_data()
        
        # Create success embed
        embed = discord.Embed(
            title="🎉 Correct Answer!",
            description=f"**{character_name}** by {message.author.mention}",
            color=0x00ff00
        )
        
        # Add character info
        char_name = character_data.get('name', {})
        full_name = char_name.get('full', character_name)
        if char_name.get('native'):
            embed.add_field(name="Native Name", value=char_name['native'], inline=True)
        
        # Add anime info
        media = character_data.get('media', {}).get('nodes', [])
        if media:
            # Filter for anime only
            anime_media = [m for m in media if m.get('type') == 'ANIME']
            if anime_media:
                anime_title = anime_media[0].get('title', {}).get('romaji', 'Unknown')
                embed.add_field(name="From Anime", value=anime_title, inline=True)
        
        embed.add_field(name="XP Gained", value=f"+{xp_gained:,} XP", inline=True)
        
        # Format time taken
        if time_taken < 60:
            time_str = f"{time_taken:.1f}s"
        elif time_taken < 3600:
            time_str = f"{time_taken/60:.1f}m"
        else:
            time_str = f"{time_taken/3600:.1f}h"
        embed.add_field(name="Response Time", value=time_str, inline=True)
        
        embed.set_footer(text=f"Total XP: {self.user_scores[guild_id][user_id]:,}")
        
        await message.reply(embed=embed)
        
        # Wait a bit then send new letter challenge
        await asyncio.sleep(3)
        await self.send_new_letter(message.channel, guild_id)

class ConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.confirmed = False

    @discord.ui.button(label='Confirm Reset', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        await interaction.response.defer()
        self.stop()

async def setup(bot):
    await bot.add_cog(AnimeNameGame(bot))