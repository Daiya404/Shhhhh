# cogs/moderation/link_fixer.py
import discord
from discord.ext import commands
from discord import app_commands
import logging

# Import our new website engine
from utils.websites import all_websites
from cogs.admin.bot_admin import BotAdmin

# The interactive view from our previous version, which is perfect for this.
class LinkFixerView(discord.ui.View):
    def __init__(self, original_author_id: int):
        super().__init__(timeout=None)
        self.original_author_id = original_author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.original_author_id:
            return True
        await interaction.response.send_message("Hmph. This isn't your message to manage.", ephemeral=True)
        return False

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.secondary, emoji="🗑️")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        await interaction.response.send_message("Fine, I've removed it.", ephemeral=True, delete_after=5)

class LinkFixer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.data_manager = self.bot.data_manager
        self.settings_cache = {} # In-memory copy of link_fixer_settings.json

    @commands.Cog.listener()
    async def on_ready(self):
        """Loads link fixer settings into memory."""
        self.logger.info("Loading link fixer settings cache...")
        self.settings_cache = await self.data_manager.get_data("link_fixer_settings")
        self.logger.info("Link Fixer settings cache is ready.")

    async def check_and_fix_link(self, message: discord.Message) -> bool:
        """Called by the Traffic Cop. Posts a new message with fixed embeds if applicable."""
        if not message.guild or message.author.bot:
            return False

        guild_settings = self.settings_cache.get(str(message.guild.id), {})
        fixed_links = []

        # Iterate through our engine of available websites
        for name, website_class in all_websites.items():
            # Check if this website is enabled for the guild (defaults to True)
            if guild_settings.get(name, True):
                matches = website_class.match(message.content)
                for match in matches:
                    fixed_links.append(website_class.fix(match))
        
        if not fixed_links:
            return False # No fixable links found

        try:
            # Join all found links into a single message
            response_content = "\n".join(fixed_links)
            view = LinkFixerView(original_author_id=message.author.id)

            await message.channel.send(response_content, view=view, allowed_mentions=discord.AllowedMentions.none())
            
            # Attempt to suppress the embed on the original message
            if message.channel.permissions_for(message.guild.me).manage_messages:
                await message.edit(suppress=True)
        except Exception as e:
            self.logger.error(f"Failed to fix link in {message.channel.name}: {e}")
            
        # We return False so other cogs (like auto-reply) can still process the original message.
        return False

    @app_commands.command(name="linkfixer-settings", description="Enable or disable fixing for specific websites.")
    @app_commands.default_permissions(administrator=True)
    @BotAdmin.is_bot_admin()
    @app_commands.describe(
        website="The website you want to configure.",
        state="Whether to turn fixing 'On' or 'Off' for this website."
    )
    @app_commands.choices(
        website=[app_commands.Choice(name=name.title(), value=name) for name in all_websites.keys()],
        state=[app_commands.Choice(name="On", value="on"), app_commands.Choice(name="Off", value="off")]
    )
    async def manage_linkfixer_settings(self, interaction: discord.Interaction, website: str, state: str):
        await interaction.response.defer() # Public response for admin transparency
        
        guild_id = str(interaction.guild.id)
        guild_settings = self.settings_cache.setdefault(guild_id, {})
        
        new_state_bool = (state == "on")
        guild_settings[website] = new_state_bool
        
        await self.data_manager.save_data("link_fixer_settings", self.settings_cache)
        
        state_text = "enabled" if new_state_bool else "disabled"
        await interaction.followup.send(f"Okay, I've **{state_text}** link fixing for **{website.title()}**.")

async def setup(bot):
    await bot.add_cog(LinkFixer(bot))