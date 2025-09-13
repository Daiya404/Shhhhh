# cogs/ai/proactive.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import random
import asyncio
from typing import Optional
from datetime import datetime, timedelta

from cogs.admin.bot_admin import is_bot_admin

class ProactiveAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.data_manager = self.bot.data_manager
        self.gemini_service = self.bot.gemini_service
        self.settings_cache = {}
        
        # Track channel activity to make more intelligent decisions
        self.channel_activity = {}
        self.last_proactive_messages = {}  # Prevent spam
        
        self.proactive_chat_task.start()

    @commands.Cog.listener()
    async def on_ready(self):
        self.settings_cache = await self.data_manager.get_data("proactive_ai_settings")
        self.logger.info("ProactiveAI settings loaded")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Track channel activity for better proactive decisions."""
        if message.author.bot or not message.guild:
            return
            
        channel_id = message.channel.id
        now = datetime.utcnow()
        
        if channel_id not in self.channel_activity:
            self.channel_activity[channel_id] = []
            
        # Track recent activity (last hour)
        cutoff = now - timedelta(hours=1)
        self.channel_activity[channel_id] = [
            activity for activity in self.channel_activity[channel_id] 
            if activity['time'] > cutoff
        ]
        
        # Add current message
        self.channel_activity[channel_id].append({
            'time': now,
            'author': message.author.display_name,
            'content': message.clean_content[:100],  # Truncate for memory
            'has_question': '?' in message.content,
            'mentions_tika': self.bot.user.mentioned_in(message)
        })

    def cog_unload(self):
        self.proactive_chat_task.cancel()

    def _analyze_conversation_context(self, messages: list, channel_activity: list) -> dict:
        """Analyze conversation to determine best proactive response type."""
        context = {
            'has_questions': any('?' in msg for msg in messages),
            'seems_confused': any(word in ' '.join(messages).lower() 
                                for word in ['confused', 'don\'t understand', 'help', 'how do']),
            'is_technical': any(word in ' '.join(messages).lower() 
                              for word in ['code', 'programming', 'error', 'bug', 'install']),
            'is_casual_chat': not any(word in ' '.join(messages).lower() 
                                    for word in ['?', 'help', 'how', 'what', 'why']),
            'high_energy': len([msg for msg in messages if '!' in msg]) > len(messages) * 0.3,
            'recent_activity_count': len(channel_activity),
            'multiple_people': len(set(activity['author'] for activity in channel_activity)) > 1
        }
        
        return context

    def _should_intervene(self, guild_id: str, channel_id: int, context: dict) -> bool:
        """Determine if Tika should speak up based on conversation context."""
        settings = self.settings_cache.get(guild_id, {})
        if not settings.get('enabled', False):
            return False
            
        base_frequency = settings.get('frequency_percent', 25)
        
        # Adjust frequency based on context
        frequency_modifier = 1.0
        
        # More likely to speak if people seem confused
        if context['seems_confused']:
            frequency_modifier *= 1.8
            
        # Less likely to interrupt casual chat between multiple people
        if context['is_casual_chat'] and context['multiple_people']:
            frequency_modifier *= 0.5
            
        # More likely to help with technical discussions
        if context['is_technical']:
            frequency_modifier *= 1.4
            
        # Less likely if channel is very active (don't spam)
        if context['recent_activity_count'] > 20:
            frequency_modifier *= 0.3
            
        # Don't speak too often in the same channel
        last_proactive = self.last_proactive_messages.get(channel_id)
        if last_proactive and (datetime.utcnow() - last_proactive).seconds < 1800:  # 30 min cooldown
            frequency_modifier *= 0.1

        adjusted_frequency = min(base_frequency * frequency_modifier, 80)  # Cap at 80%
        
        return random.randint(1, 100) <= adjusted_frequency

    @tasks.loop(minutes=12)  # Slightly more frequent than before
    async def proactive_chat_task(self):
        """Main proactive chat task with improved decision making."""
        if not self.settings_cache or not self.gemini_service.is_ready():
            return
            
        for guild_id_str, settings in self.settings_cache.items():
            try:
                await self._process_guild_proactive(guild_id_str, settings)
            except Exception as e:
                self.logger.error(f"Error in proactive chat for guild {guild_id_str}: {e}")

    async def _process_guild_proactive(self, guild_id_str: str, settings: dict):
        """Process proactive chat for a single guild."""
        channel_id = settings.get("channel_id")
        if not channel_id:
            return
            
        guild = self.bot.get_guild(int(guild_id_str))
        if not guild:
            return
            
        channel = guild.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        # Check if channel has recent activity
        if not channel.last_message_id:
            return
            
        last_message_time = discord.utils.snowflake_time(channel.last_message_id)
        time_since_last = (discord.utils.utcnow() - last_message_time).total_seconds()
        
        # Don't interrupt if too recent (< 2 min) or too old (> 15 min)
        if time_since_last < 120 or time_since_last > 900:
            return

        try:
            # Get recent conversation
            messages = []
            async for msg in channel.history(limit=15):
                if not msg.author.bot and msg.clean_content.strip():
                    messages.append(f"{msg.author.display_name}: {msg.clean_content}")
                    
            if len(messages) < 3:  # Need some context
                return
                
            messages.reverse()  # Chronological order
            
            # Analyze context
            channel_activity = self.channel_activity.get(channel_id, [])
            context = self._analyze_conversation_context(messages, channel_activity)
            
            # Decide whether to speak
            if not self._should_intervene(guild_id_str, channel_id, context):
                return

            # Generate proactive comment
            comment = await self.gemini_service.generate_proactive_comment(messages)
            
            if comment and len(comment.strip()) > 0:
                # Add realistic delay
                typing_time = len(comment) * 0.03 + random.uniform(0.5, 2.0)
                
                async with channel.typing():
                    await asyncio.sleep(min(typing_time, 4.0))
                    await channel.send(comment)
                    
                self.last_proactive_messages[channel_id] = datetime.utcnow()
                self.logger.info(f"Sent proactive message in {channel.name}: {comment[:50]}...")
                
        except discord.Forbidden:
            self.logger.warning(f"No permission to send proactive message in {channel.name}")
        except Exception as e:
            self.logger.error(f"Failed to send proactive message in {channel.name}: {e}")

    @proactive_chat_task.before_loop
    async def before_proactive_chat_task(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="proactive-ai", description="[Admin] Configure Tika's ability to comment on conversations.")
    @app_commands.default_permissions(administrator=True)
    @is_bot_admin()
    @app_commands.describe(
        action="The action to perform.",
        channel="The channel for Tika to monitor.",
        frequency="How often Tika should consider speaking (%). Higher = more talkative."
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Configure", value="config"),
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
        app_commands.Choice(name="View Status", value="status"),
        app_commands.Choice(name="Test Comment", value="test")
    ])
    async def proactive_settings(
        self, 
        interaction: discord.Interaction, 
        action: str, 
        channel: Optional[discord.TextChannel] = None, 
        frequency: Optional[app_commands.Range[int, 1, 100]] = None
    ):
        await interaction.response.defer(ephemeral=True)
        
        guild_id_str = str(interaction.guild_id)
        guild_settings = self.settings_cache.setdefault(guild_id_str, {})

        if action == "status":
            await self._show_status(interaction, guild_settings)
        elif action == "enable":
            await self._enable_proactive(interaction, guild_settings)
        elif action == "disable":
            await self._disable_proactive(interaction, guild_settings)
        elif action == "config":
            await self._configure_proactive(interaction, guild_settings, channel, frequency)
        elif action == "test":
            await self._test_proactive(interaction, guild_settings)

    async def _show_status(self, interaction: discord.Interaction, guild_settings: dict):
        """Show current proactive AI status."""
        is_enabled = guild_settings.get("enabled", False)
        monitored_channel_id = guild_settings.get("channel_id")
        monitored_channel = self.bot.get_channel(monitored_channel_id) if monitored_channel_id else None
        current_freq = guild_settings.get("frequency_percent", 25)
        
        embed = discord.Embed(
            title="🤖 Proactive AI Status",
            color=discord.Color.green() if is_enabled else discord.Color.red(),
            description="Current configuration for Tika's proactive commenting"
        )
        
        embed.add_field(
            name="State", 
            value="✅ Enabled" if is_enabled else "❌ Disabled",
            inline=True
        )
        embed.add_field(
            name="Monitored Channel", 
            value=monitored_channel.mention if monitored_channel else "❌ Not Set",
            inline=True
        )
        embed.add_field(
            name="Base Frequency", 
            value=f"{current_freq}%",
            inline=True
        )
        
        if monitored_channel_id in self.last_proactive_messages:
            last_comment = self.last_proactive_messages[monitored_channel_id]
            time_since = (datetime.utcnow() - last_comment).total_seconds() / 60
            embed.add_field(
                name="Last Comment",
                value=f"{time_since:.0f} minutes ago",
                inline=True
            )
            
        embed.set_footer(text="Frequency is dynamically adjusted based on conversation context")
        await interaction.followup.send(embed=embed)

    async def _enable_proactive(self, interaction: discord.Interaction, guild_settings: dict):
        """Enable proactive AI."""
        if not guild_settings.get("channel_id"):
            await interaction.followup.send(
                "❌ You must configure a channel first using the `config` action.\n"
                "*I can't just start talking randomly everywhere. That would be chaos.*"
            )
            return
            
        guild_settings["enabled"] = True
        await self.data_manager.save_data("proactive_ai_settings", self.settings_cache)
        
        channel = self.bot.get_channel(guild_settings["channel_id"])
        await interaction.followup.send(
            f"✅ **Proactive AI Enabled**\n"
            f"*Fine, I'll start paying attention to conversations in {channel.mention}. "
            f"Don't blame me if I interrupt something important.*"
        )

    async def _disable_proactive(self, interaction: discord.Interaction, guild_settings: dict):
        """Disable proactive AI."""
        guild_settings["enabled"] = False
        await self.data_manager.save_data("proactive_ai_settings", self.settings_cache)
        
        responses = [
            "✅ **Proactive AI Disabled**\n*Finally. I was getting tired of listening to you all anyway.*",
            "✅ **Proactive AI Disabled**\n*Alright, I'll go back to ignoring your conversations. You're welcome.*",
            "✅ **Proactive AI Disabled**\n*Good. Now I can focus on more important things than your chatter.*"
        ]
        
        await interaction.followup.send(random.choice(responses))

    async def _configure_proactive(self, interaction: discord.Interaction, guild_settings: dict, channel: discord.TextChannel, frequency: int):
        """Configure proactive AI settings."""
        if not channel or frequency is None:
            await interaction.followup.send(
                "❌ You must provide both a `channel` and a `frequency` to configure.\n"
                "*I need to know where to talk and how much. Be specific.*"
            )
            return
            
        guild_settings["channel_id"] = channel.id
        guild_settings["frequency_percent"] = frequency
        await self.data_manager.save_data("proactive_ai_settings", self.settings_cache)
        
        frequency_desc = "very chatty" if frequency > 60 else "moderately talkative" if frequency > 30 else "pretty quiet"
        
        await interaction.followup.send(
            f"✅ **Proactive AI Configured**\n"
            f"📍 **Channel:** {channel.mention}\n"
            f"🎯 **Base Frequency:** {frequency}% ({frequency_desc})\n\n"
            f"*I'll monitor {channel.mention} and consider commenting about {frequency}% of the time. "
            f"The actual frequency will adjust based on context - I'm not completely thoughtless.*"
        )

    async def _test_proactive(self, interaction: discord.Interaction, guild_settings: dict):
        """Test proactive AI by generating a comment on recent messages."""
        if not self.gemini_service.is_ready():
            await interaction.followup.send(
                "❌ My AI brain is offline. Can't test anything right now.\n"
                "*Figures. When you actually want me to work, I'm broken.*"
            )
            return
            
        channel_id = guild_settings.get("channel_id")
        if not channel_id:
            await interaction.followup.send(
                "❌ No channel configured. Use the `config` action first.\n"
                "*How am I supposed to comment on nothing?*"
            )
            return
            
        channel = self.bot.get_channel(channel_id)
        if not channel:
            await interaction.followup.send(
                "❌ Configured channel not found. It might have been deleted.\n"
                "*Great, now I'm talking to the void.*"
            )
            return

        try:
            # Get recent messages
            messages = []
            async for msg in channel.history(limit=10):
                if not msg.author.bot and msg.clean_content.strip():
                    messages.append(f"{msg.author.display_name}: {msg.clean_content}")
                    
            if len(messages) < 3:
                await interaction.followup.send(
                    f"❌ Not enough conversation in {channel.mention} to generate a test comment.\n"
                    "*There's literally nothing interesting to comment on.*"
                )
                return
                
            messages.reverse()
            
            # Generate test comment
            await interaction.response.edit_original_response(content="🤔 *Analyzing conversation...*")
            
            comment = await self.gemini_service.generate_proactive_comment(messages)
            
            if comment:
                embed = discord.Embed(
                    title="🧪 Test Proactive Comment",
                    description=f"Based on recent conversation in {channel.mention}:",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="Generated Comment:",
                    value=f'"{comment}"',
                    inline=False
                )
                embed.set_footer(text="This is just a test - the comment wasn't actually sent")
                
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(
                    "❌ Couldn't generate a test comment. The conversation might be too boring.\n"
                    "*Even I have standards about what's worth commenting on.*"
                )
                
        except Exception as e:
            self.logger.error(f"Test proactive comment failed: {e}")
            await interaction.followup.send(
                "❌ Something went wrong during the test. Typical.\n"
                "*My brain decided to take a break at the worst possible moment.*"
            )

async def setup(bot):
    if hasattr(bot, 'gemini_service') and bot.gemini_service and bot.gemini_service.is_ready():
        await bot.add_cog(ProactiveAI(bot))
        logging.getLogger(__name__).info("ProactiveAI cog loaded successfully")
    else:
        logging.getLogger(__name__).warning(
            "Skipping ProactiveAI cog - Gemini Service not available"
        )