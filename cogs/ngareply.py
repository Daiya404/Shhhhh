import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import re
from pathlib import Path
import logging

class NgaReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.data_file = Path('data/nga_replies.json')
        self.triggers = self.load_triggers()
    
    def load_triggers(self):
        """Load trigger data from JSON file"""
        try:
            if self.data_file.exists():
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.logger.error(f"Error loading triggers: {e}")
            return {}
    
    def save_triggers(self):
        """Save trigger data to JSON file"""
        try:
            # Ensure data directory exists
            self.data_file.parent.mkdir(exist_ok=True)
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.triggers, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving triggers: {e}")
    
    def is_url(self, text):
        """Check if text is a URL"""
        url_pattern = re.compile(
            r'https?://(?:[-\w.])+(?::[0-9]+)?(?:/(?:[\w/_.])*(?:\?(?:[\w&=%.])*)?(?:#(?:[\w.])*)?)?',
            re.IGNORECASE
        )
        return bool(url_pattern.match(text.strip()))
    
    @app_commands.command(name="nga", description="Set up a trigger word with a custom reply")
    @app_commands.describe(
        text="The trigger word/phrase",
        reply="The reply (text, image URL, or GIF URL)"
    )
    async def nga_setup(self, interaction: discord.Interaction, text: str, reply: str):
        """Set up a new trigger word with reply"""
        # Check if user has manage messages permission
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ You need 'Manage Messages' permission to use this command!", 
                ephemeral=True
            )
            return
        
        guild_id = str(interaction.guild.id)
        trigger_key = text.lower().strip()
        
        # Initialize guild data if not exists
        if guild_id not in self.triggers:
            self.triggers[guild_id] = {}
        
        # Create or update trigger
        self.triggers[guild_id][trigger_key] = {
            "main_word": text,
            "alternatives": [],
            "reply": reply,
            "created_by": interaction.user.id,
            "created_at": interaction.created_at.isoformat()
        }
        
        self.save_triggers()
        
        embed = discord.Embed(
            title="✅ Trigger Set Up",
            color=0x00ff00,
            description=f"**Trigger:** `{text}`\n**Reply:** {reply[:100]}{'...' if len(reply) > 100 else ''}"
        )
        embed.set_footer(text=f"Created by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="nga-add", description="Add alternative words to an existing trigger")
    @app_commands.describe(
        alternative="The alternative word/phrase to add",
        main_trigger="The main trigger word this alternative belongs to"
    )
    async def nga_add_alternative(self, interaction: discord.Interaction, alternative: str, main_trigger: str):
        """Add alternative words to existing trigger"""
        # Check if user has manage messages permission
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ You need 'Manage Messages' permission to use this command!", 
                ephemeral=True
            )
            return
        
        # Input validation
        if len(alternative.strip()) == 0 or len(main_trigger.strip()) == 0:
            await interaction.response.send_message(
                "❌ Alternative and main trigger cannot be empty!", 
                ephemeral=True
            )
            return
        
        guild_id = str(interaction.guild.id)
        main_key = main_trigger.lower().strip()
        alt_key = alternative.lower().strip()
        
        # Check if main trigger exists
        if guild_id not in self.triggers or main_key not in self.triggers[guild_id]:
            await interaction.response.send_message(
                f"❌ Main trigger `{main_trigger}` not found! Use `/nga` to create it first.", 
                ephemeral=True
            )
            return
        
        # Check if alternative already exists
        if alt_key in self.triggers[guild_id][main_key]["alternatives"]:
            await interaction.response.send_message(
                f"❌ Alternative `{alternative}` already exists for `{main_trigger}`!", 
                ephemeral=True
            )
            return
        
        # Add alternative
        self.triggers[guild_id][main_key]["alternatives"].append(alt_key)
        self.save_triggers()
        
        embed = discord.Embed(
            title="✅ Alternative Added",
            color=0x00ff00,
            description=f"**Alternative:** `{alternative}`\n**Added to trigger:** `{main_trigger}`"
        )
        
        # Show all alternatives
        all_alts = self.triggers[guild_id][main_key]["alternatives"]
        if all_alts:
            embed.add_field(
                name="All Alternatives",
                value=", ".join([f"`{alt}`" for alt in all_alts[:10]]) + ("..." if len(all_alts) > 10 else ""),
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="nga-list", description="List all triggers and their alternatives")
    async def nga_list(self, interaction: discord.Interaction):
        """List all triggers for this server"""
        guild_id = str(interaction.guild.id)
        
        if guild_id not in self.triggers or not self.triggers[guild_id]:
            await interaction.response.send_message("📝 No triggers set up for this server yet!")
            return
        
        embed = discord.Embed(
            title="📋 Server Triggers",
            color=0x3498db,
            description="List of all active triggers"
        )
        
        for main_word, data in self.triggers[guild_id].items():
            alternatives_text = ""
            if data["alternatives"]:
                alternatives_text = f"\n**Alternatives:** {', '.join([f'`{alt}`' for alt in data['alternatives']])}"
            
            reply_preview = data["reply"][:50] + "..." if len(data["reply"]) > 50 else data["reply"]
            
            embed.add_field(
                name=f"🎯 {data['main_word']}",
                value=f"**Reply:** {reply_preview}{alternatives_text}",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="nga-remove", description="Remove a trigger")
    @app_commands.describe(trigger="The main trigger word to remove")
    async def nga_remove(self, interaction: discord.Interaction, trigger: str):
        """Remove a trigger"""
        # Check if user has manage messages permission
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ You need 'Manage Messages' permission to use this command!", 
                ephemeral=True
            )
            return
        
        guild_id = str(interaction.guild.id)
        trigger_key = trigger.lower().strip()
        
        if guild_id not in self.triggers or trigger_key not in self.triggers[guild_id]:
            await interaction.response.send_message(
                f"❌ Trigger `{trigger}` not found!", 
                ephemeral=True
            )
            return
        
        # Remove trigger
        del self.triggers[guild_id][trigger_key]
        self.save_triggers()
        
        embed = discord.Embed(
            title="🗑️ Trigger Removed",
            color=0xff0000,
            description=f"Trigger `{trigger}` and all its alternatives have been removed."
        )
        
        await interaction.response.send_message(embed=embed)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for trigger words in messages"""
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Ignore if no guild
        if not message.guild:
            return
        
        guild_id = str(message.guild.id)
        
        # Check if guild has any triggers
        if guild_id not in self.triggers or not self.triggers[guild_id]:
            return
        
        message_content = message.content.lower().strip()
        
        # Early return if message is empty
        if not message_content:
            return
        
        # Check each trigger
        for main_word, data in self.triggers[guild_id].items():
            # Use word boundaries for better matching
            pattern = r'\b' + re.escape(main_word) + r'\b'
            if re.search(pattern, message_content):
                await self.send_reply(message, data)
                return
            
            # Check alternatives with word boundaries
            for alternative in data["alternatives"]:
                alt_pattern = r'\b' + re.escape(alternative) + r'\b'
                if re.search(alt_pattern, message_content):
                    await self.send_reply(message, data)
                    return
    
    async def send_reply(self, message, trigger_data):
        """Send the reply for a triggered word"""
        try:
            reply = trigger_data["reply"]
            
            # Check if reply is a URL (image/gif)
            if self.is_url(reply):
                embed = discord.Embed(color=0x3498db)
                embed.set_image(url=reply)
                await message.reply(embed=embed, mention_author=False)
            else:
                # Send as regular text
                await message.reply(reply, mention_author=False)
                
        except discord.HTTPException as e:
            self.logger.error(f"HTTP error sending nga reply: {e}")
        except discord.Forbidden:
            self.logger.warning(f"No permission to send message in {message.guild.name}")
        except Exception as e:
            self.logger.error(f"Unexpected error sending nga reply: {e}")

async def setup(bot):
    await bot.add_cog(NgaReply(bot))