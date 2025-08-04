import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
from pathlib import Path
import logging
import time
from typing import Dict

from .bot_admin import BotAdmin

# Personality for this Cog
PERSONALITY = {
    "channel_set": "Understood. From now on, all detention sentences will be served in {channel}.",
    "no_channel_set": "An admin needs to set a detention channel first using `/detention set-channel`.",
    "detention_start": "Done. {user} has been placed in detention. I've created instructions for them in {channel}.",
    "milestone_progress": "You're making progress, {user}. Only `{remaining}` more to go.",
    "detention_done": "Hmph. You finished. I've restored your roles. Try to be less of a problem from now on.",
    "detention_released": "Fine, I've released {user} from detention. I hope you know what you're doing.",
    "missing_role": "I can't do my job if you haven't done yours. A role named `BEHAVE` needs to exist first.",
    "cant_manage_user": "I can't manage `{user}`. Their role is higher than mine. That's a 'you' problem, not a 'me' problem.",
    "cant_manage_role": "The `BEHAVE` role is above my top role. I can't assign it to anyone. Move it down.",
    "already_detained": "That user is already in detention. Don't waste my time.",
    "not_detained": "That user isn't in detention. I can't release someone who is already free.",
    "no_one_detained": "No one is in detention. The server is behaving... for now.",
    "self_detention": "Don't be ridiculous. I'm not putting you in detention.",
    "bot_detention": "You can't put a bot in detention. It wouldn't learn anything.",
    "channel_perms_missing": "I can't work in that channel. I need permissions to Send Messages, Manage Messages (for pinning), and Add Reactions."
}

class Detention(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.settings_file = Path("data/role_settings.json")
        self.detention_file = Path("data/detention_data.json")
        self.settings_data: Dict[str, Dict] = self._load_json(self.settings_file)
        self.detention_data: Dict[str, dict] = self._load_json(self.detention_file)

    @commands.Cog.listener()
    async def on_ready(self):
        pass

    # Public methods for main.py to call
    async def is_user_detained(self, message: discord.Message) -> bool:
        if not message.guild: return False
        return str(message.guild.id) in self.detention_data and str(message.author.id) in self.detention_data[str(message.guild.id)]

    async def handle_detention_message(self, message: discord.Message):
        guild_id, user_id = str(message.guild.id), str(message.author.id)
        detention_channel_id = self.settings_data.get(guild_id, {}).get("detention_channel_id")
        
        if not detention_channel_id or message.channel.id != detention_channel_id:
            try: return await message.delete()
            except discord.NotFound: return

        data = self.detention_data[guild_id][user_id]
        if message.content.strip() == data["sentence"]:
            data["reps_remaining"] -= 1
            
            try: await message.add_reaction("✅")
            except discord.Forbidden: pass # Can't add reaction, but proceed anyway
            
            # Update the pinned message
            await self._update_pinned_message(message.guild, message.author)

            # Check for milestones
            total_reps = data.get("total_reps", data["reps_remaining"] + 1)
            if data["reps_remaining"] == round(total_reps / 2) or data["reps_remaining"] == 10:
                progress_msg = PERSONALITY["milestone_progress"].format(user=message.author.mention, remaining=data['reps_remaining'])
                try: await message.channel.send(progress_msg, delete_after=10)
                except discord.HTTPException: pass
            
            if data["reps_remaining"] <= 0:
                await self._release_from_detention(message.guild, message.author)
            else:
                await self._save_json(self.detention_data, self.detention_file)
        else:
            try: await message.delete()
            except discord.NotFound: pass

    # Data Handling
    def _load_json(self, file_path: Path) -> Dict:
        if not file_path.exists(): return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Error loading {file_path}", exc_info=True)
            return {}

    async def _save_json(self, data: dict, file_path: Path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except IOError as e:
            self.logger.error(f"Error saving {file_path}", exc_info=True)
            
    # Command Group
    detention_group = app_commands.Group(name="detention", description="Commands for managing the user detention system.")

    @detention_group.command(name="set-channel", description="Set the channel where users must serve detention.")
    @app_commands.describe(channel="The channel to use for all detentions.")
    @BotAdmin.is_bot_admin()
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        # Permission Check
        perms = channel.permissions_for(interaction.guild.me)
        if not all([perms.send_messages, perms.manage_messages, perms.add_reactions, perms.read_message_history]):
            return await interaction.response.send_message(PERSONALITY["channel_perms_missing"], ephemeral=True)

        guild_id = str(interaction.guild.id)
        self.settings_data.setdefault(guild_id, {})["detention_channel_id"] = channel.id
        await self._save_json(self.settings_data, self.settings_file)
        await interaction.response.send_message(PERSONALITY["channel_set"].format(channel=channel.mention), ephemeral=True)

    @detention_group.command(name="start", description="Put a user in detention, forcing them to type a sentence.")
    @app_commands.describe(user="The user to put in detention.", sentence="The sentence to type (max 150 chars).", repetitions="How many times (1-100).")
    @BotAdmin.is_bot_admin()
    async def start(self, interaction: discord.Interaction, user: discord.Member, sentence: app_commands.Range[str, 1, 150], repetitions: app_commands.Range[int, 1, 100]):
        guild_id, user_id = str(interaction.guild.id), str(user.id)
        
        detention_channel_id = self.settings_data.get(guild_id, {}).get("detention_channel_id")
        detention_channel = interaction.guild.get_channel(detention_channel_id) if detention_channel_id else None
        if not detention_channel:
            return await interaction.response.send_message(PERSONALITY["no_channel_set"], ephemeral=True)
        
        if user.bot or user == interaction.user or self.detention_data.get(guild_id, {}).get(user_id):
            # Simplified validation checks
            reason = PERSONALITY["bot_detention"] if user.bot else PERSONALITY["self_detention"] if user == interaction.user else PERSONALITY["already_detained"]
            return await interaction.response.send_message(reason, ephemeral=True)
            
        detention_role = discord.utils.get(interaction.guild.roles, name="BEHAVE")
        if not detention_role or detention_role.position >= interaction.guild.me.top_role.position:
            reason = PERSONALITY["missing_role"] if not detention_role else PERSONALITY["cant_manage_role"]
            return await interaction.response.send_message(reason, ephemeral=True)

        original_roles = [role.id for role in user.roles if not role.is_default()]
        try:
            await user.edit(roles=[detention_role], reason=f"Detention by {interaction.user.display_name}")
        except discord.Forbidden:
            return await interaction.response.send_message(PERSONALITY["cant_manage_user"].format(user=user.display_name), ephemeral=True)
        
        # Create and pin the instruction message
        pin_embed = self._create_pin_embed(user, sentence, repetitions)
        pin_message = await detention_channel.send(embed=pin_embed)
        await pin_message.pin(reason=f"Detention pin for {user.display_name}")

        self.detention_data.setdefault(guild_id, {})[user_id] = {
            "sentence": sentence, "reps_remaining": repetitions, "total_reps": repetitions,
            "original_roles": original_roles, "pin_message_id": pin_message.id,
            "detained_by_id": interaction.user.id, "start_timestamp": int(time.time())
        }
        await self._save_json(self.detention_data, self.detention_file)
        await interaction.response.send_message(PERSONALITY["detention_start"].format(user=user.mention, channel=detention_channel.mention))

    @detention_group.command(name="release", description="Manually release a user from detention.")
    @app_commands.describe(user="The user to release from detention.")
    @BotAdmin.is_bot_admin()
    async def release(self, interaction: discord.Interaction, user: discord.Member):
        guild_id, user_id = str(interaction.guild.id), str(user.id)
        if not self.detention_data.get(guild_id, {}).get(user_id):
            return await interaction.response.send_message(PERSONALITY["not_detained"], ephemeral=True)
        await self._release_from_detention(interaction.guild, user)
        await interaction.response.send_message(PERSONALITY["detention_released"].format(user=user.mention), ephemeral=True)

    @detention_group.command(name="list", description="List all users currently in detention.")
    @BotAdmin.is_bot_admin()
    async def list(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        detained_users = self.detention_data.get(guild_id, {})
        if not detained_users:
            return await interaction.response.send_message(PERSONALITY["no_one_detained"], ephemeral=True)

        embed = discord.Embed(title="Users Currently in Detention", color=discord.Color.orange())
        for user_id, data in detained_users.items():
            member = interaction.guild.get_member(int(user_id))
            name = member.display_name if member else f"Unknown User ({user_id})"
            detained_by = f"<@{data.get('detained_by_id', 'Unknown')}>"
            timestamp = f"<t:{data.get('start_timestamp', '0')}:R>"
            embed.add_field(
                name = name,
                value = f"**Remaining:** {data['reps_remaining']} / {data['total_reps']}\n"
                        f"**Detained By:** {detained_by} ({timestamp})",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _create_pin_embed(self, user: discord.Member, sentence: str, remaining: int) -> discord.Embed:
        embed = discord.Embed(
            title=f"Detention for {user.display_name}",
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Sentence to Type", value=f"```{sentence}```", inline=False)
        embed.add_field(name="Repetitions Remaining", value=f"**{remaining}**", inline=False)
        return embed

    async def _update_pinned_message(self, guild: discord.Guild, user: discord.Member):
        guild_id, user_id = str(guild.id), str(user.id)
        data = self.detention_data.get(guild_id, {}).get(user_id)
        if not data or "pin_message_id" not in data: return

        detention_channel_id = self.settings_data.get(guild_id, {}).get("detention_channel_id")
        if not detention_channel_id: return

        channel = guild.get_channel(detention_channel_id)
        if not channel: return

        try:
            msg = await channel.fetch_message(data["pin_message_id"])
            new_embed = self._create_pin_embed(user, data["sentence"], data["reps_remaining"])
            await msg.edit(embed=new_embed)
        except discord.NotFound:
            self.logger.warning(f"Detention pin for {user.id} not found. Could not update.")
        except Exception as e:
            self.logger.error(f"Failed to update pin for {user.id}: {e}", exc_info=True)

    async def _release_from_detention(self, guild: discord.Guild, user: discord.Member):
        guild_id, user_id = str(guild.id), str(user.id)
        data = self.detention_data.get(guild_id, {}).pop(user_id, None)
        if data is None: return
        
        if "pin_message_id" in data:
            detention_channel_id = self.settings_data.get(guild_id, {}).get("detention_channel_id")
            if detention_channel_id:
                channel = guild.get_channel(detention_channel_id)
                if channel:
                    try:
                        msg = await channel.fetch_message(data["pin_message_id"])
                        await msg.unpin(reason="Detention completed.")
                        await msg.delete()
                    except (discord.NotFound, discord.Forbidden): pass # Ignore if already gone or no perms

        if not self.detention_data[guild_id]: del self.detention_data[guild_id]

        roles_to_restore = [guild.get_role(rid) for rid in data.get("original_roles", []) if guild.get_role(rid)]
        try:
            await user.edit(roles=roles_to_restore, reason="Released from detention.")
        except discord.Forbidden:
            self.logger.error(f"Failed to restore roles for {user.display_name} in {guild.name}.")
        
        await self._save_json(self.detention_data, self.detention_file)
        
        if data.get('reps_remaining', 1) <= 0:
            detention_channel_id = self.settings_data.get(guild_id, {}).get("detention_channel_id")
            if detention_channel_id and (channel := guild.get_channel(detention_channel_id)):
                await channel.send(PERSONALITY["detention_done"].format(user=user.mention))

async def setup(bot):
    await bot.add_cog(Detention(bot))