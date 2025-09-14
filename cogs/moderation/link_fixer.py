# cogs/moderation/link_fixer.py
import discord
from discord.ext import commands
from discord import app_commands
import logging

from utils.websites import all_websites
from config.personalities import PERSONALITY_RESPONSES

class LinkFixerView(discord.ui.View):
    def __init__(self, original_message_id: int, original_channel_id: int, original_author_id: int, source_url: str):
        super().__init__(timeout=None)
        self.original_message_id = original_message_id
        self.original_channel_id = original_channel_id
        self.original_author_id = original_author_id
        self.add_item(discord.ui.Button(label="Source", style=discord.ButtonStyle.link, url=source_url))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.original_author_id:
            return True
        await interaction.response.send_message("Hmph. This isn't your message to manage.", ephemeral=True)
        return False

    @discord.ui.button(label="Revert", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def revert_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        try:
            channel = interaction.client.get_channel(self.original_channel_id)
            if channel:
                original_message = await channel.fetch_message(self.original_message_id)
                await original_message.edit(suppress=False)
        except (discord.NotFound, discord.Forbidden):
            pass
        await interaction.response.send_message("Fine, I've reverted it.", ephemeral=True, delete_after=5)

class LinkFixer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["link_fixer"]
        self.data_manager = self.bot.data_manager
        self.settings_cache = {}

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info("Loading link fixer settings cache...")
        self.settings_cache = await self.data_manager.get_data("link_fixer_settings")
        self.logger.info("Link Fixer settings cache is ready.")

    async def check_and_fix_link(self, message: discord.Message) -> bool:
        if not message.guild or message.author.bot:
            return False

        user_settings = self.settings_cache.get(str(message.guild.id), {}).get("users", {}).get(str(message.author.id), {})
        response_parts = []
        original_url_for_view = None

        for name, website_class in all_websites.items():
            if user_settings.get(name, True):
                for match in website_class.pattern.finditer(message.content):
                    link_data = await website_class.get_links(match, session=self.bot.http_session)
                    if link_data:
                        part = ""
                        # --- CORRECTED FORMATTING WITH NON-EMBEDDING LINKS ---

                        # Case 1: API-based fix (like Instagram/EmbedEZ)
                        if link_data.get("fixer_name"):
                            # The original URL is now wrapped in <> to prevent a double embed
                            part = f"[{link_data['display_name']}](<{link_data['original_url']}>) • [{link_data['fixer_name']}]({link_data['fixed_url']})"
                        
                        # Case 2: Link with author info (like Twitter)
                        elif link_data.get("author_name"):
                            # The profile URL is now wrapped in <> to prevent a double embed
                            part = f"[{link_data['display_name']}]({link_data['fixed_url']}) • [{link_data['author_name']}](<{link_data['profile_url']}>)"
                        
                        # Case 3: Simple link with no author (like Pixiv)
                        else:
                            # This only has one link, so it should embed normally. No change needed.
                            part = f"[{link_data['display_name']}]({link_data['fixed_url']})"
                            
                        response_parts.append(part)
                        if not original_url_for_view:
                            original_url_for_view = link_data['original_url']

        if not response_parts:
            return False

        try:
            response_content = "\n".join(response_parts)
            view = LinkFixerView(
                original_message_id=message.id,
                original_channel_id=message.channel.id,
                original_author_id=message.author.id,
                source_url=original_url_for_view
            )
            await message.reply(response_content, view=view, allowed_mentions=discord.AllowedMentions.none())
            if message.channel.permissions_for(message.guild.me).manage_messages:
                await message.edit(suppress=True)
        except Exception as e:
            self.logger.error(f"Failed to fix link in {message.channel.name}: {e}")
        return False

    @app_commands.command(name="linkfixer-settings", description="Enable or disable link fixing for yourself.")
    @app_commands.describe(website="The website you want to configure for yourself.", state="Whether to turn fixing 'On' or 'Off' for your links.")
    @app_commands.choices(
        website=[app_commands.Choice(name=name.title(), value=name) for name in sorted(all_websites.keys())],
        state=[app_commands.Choice(name="On", value="on"), app_commands.Choice(name="Off", value="off")]
    )
    async def manage_linkfixer_settings(self, interaction: discord.Interaction, website: str, state: str):
        await interaction.response.defer(ephemeral=True)
        guild_id, user_id = str(interaction.guild.id), str(interaction.user.id)
        guild_settings = self.settings_cache.setdefault(guild_id, {"users": {}})
        user_settings = guild_settings.setdefault("users", {}).setdefault(user_id, {})
        new_state_bool = (state == "on")
        user_settings[website] = new_state_bool
        await self.data_manager.save_data("link_fixer_settings", self.settings_cache)
        if new_state_bool:
            response_msg = self.personality['personal_opt_in']
        else:
            response_msg = self.personality['personal_opt_out']
        await interaction.followup.send(response_msg)

async def setup(bot):
    await bot.add_cog(LinkFixer(bot))