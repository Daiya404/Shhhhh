# core/bot.py
import discord
from discord.ext import commands
import logging
from collections import defaultdict

from config.settings import Settings
from services.data_manager import DataManager

class TikaBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True
        super().__init__(command_prefix=settings.COMMAND_PREFIX, intents=intents, help_command=None)
        
        self.settings = settings
        self.logger = logging.getLogger('discord')
        
        self.data_manager = DataManager(base_path=self.settings.DATA_DIR)
        self.command_usage = defaultdict(lambda: defaultdict(list))

    async def setup_hook(self):
        # ... (setup hook logic remains the same) ...
        self.logger.info("--- Tika is waking up... ---")
        self.settings.DATA_DIR.mkdir(exist_ok=True); self.settings.LOGS_DIR.mkdir(exist_ok=True)
        loaded_cogs = 0
        for folder in self.settings.COGS_DIR.iterdir():
            if folder.is_dir():
                for file in folder.glob("*.py"):
                    if not file.name.startswith("_"):
                        try:
                            extension = f"cogs.{folder.name}.{file.stem}"
                            await self.load_extension(extension)
                            self.logger.info(f"✅ Loaded Cog: {extension}")
                            loaded_cogs += 1
                        except Exception as e:
                            self.logger.error(f"❌ Failed to load Cog: {extension}", exc_info=e)
        self.logger.info(f"--- Loaded {loaded_cogs} cog(s) successfully. ---")
        synced = await self.tree.sync()
        self.logger.info(f"🔄 Synced {len(synced)} application command(s) globally.")

    async def on_message(self, message: discord.Message):
        """The Traffic Cop: Checks every message and enforces high-priority rules."""
        if message.author.bot:
            return

        # --- DETENTION ENFORCEMENT LOGIC ---
        detention_cog = self.get_cog("Detention")
        if detention_cog and await detention_cog.is_user_detained(message):
            # The user is in detention. We must handle their message.
            
            settings_data = await self.data_manager.get_data("role_settings")
            detention_channel_id = settings_data.get(str(message.guild.id), {}).get("detention_channel_id")

            # Check if the message is OUTSIDE the detention channel
            if detention_channel_id and message.channel.id != detention_channel_id:
                try:
                    await message.delete()
                    # Optionally send a public warning that deletes itself to avoid clutter
                    await message.channel.send(f"{message.author.mention}, you are in detention. You can only speak in the designated channel.", delete_after=7)
                except (discord.Forbidden, discord.NotFound):
                    # Bot lacks permissions or the message was already deleted.
                    pass
                finally:
                    # IMPORTANT: Stop any other bot functions from running for this message.
                    return
            
            # If the message is INSIDE the detention channel, pass it to the cog to be processed.
            else:
                await detention_cog.handle_detention_message(message)
                return # Stop processing here.

        # --- End of Detention Logic ---

        word_blocker_cog = self.get_cog("WordBlocker")
        if word_blocker_cog and await word_blocker_cog.check_and_handle_message(message):
            return # If message was deleted, we're done.

        link_fixer_cog = self.get_cog("LinkFixer")
        if link_fixer_cog:
            await link_fixer_cog.check_and_fix_link(message)

        auto_reply_cog = self.get_cog("AutoReply")
        if auto_reply_cog and await auto_reply_cog.check_for_reply(message):
            return # If a reply was sent, we're done.

        ctx = await self.get_context(message)
        if ctx.valid:
            await self.invoke(ctx)

    async def on_ready(self):
        # ... (on_ready logic remains the same) ...
        activity = discord.Game(name="Doing things. Perfectly, of course."); await self.change_presence(status=discord.Status.online, activity=activity); self.logger.info("---"); self.logger.info(f"Logged in as: {self.user} (ID: {self.user.id})"); self.logger.info(f"Serving {len(self.guilds)} server(s)."); self.logger.info(f"Discord.py Version: {discord.__version__}"); self.logger.info(f"--- Tika is now online and ready! ---")