# cogs/help.py
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

class Help(commands.Cog):
    """Help and documentation commands."""
    
    def __init__(self, bot):
        self.bot = bot
        self.personality = bot.personality
    
    @app_commands.command(name="help", description="Show available commands and features")
    @app_commands.describe(category="Specific category to get help for")
    async def help_command(
        self, 
        interaction: discord.Interaction, 
        category: Optional[str] = None
    ):
        """Display help information."""
        try:
            if not await self.bot.feature_manager.is_enabled(interaction.guild.id, "help"):
                return await interaction.response.send_message(
                    self.personality.get("general", "feature_disabled"),
                    ephemeral=True
                )
            
            # Get available cogs and their commands
            available_cogs = {}
            is_admin = await self.bot.admin_manager.is_bot_admin(interaction.user)
            
            for cog_name, cog in self.bot.cogs.items():
                if cog_name.startswith('_'):
                    continue
                
                # Get commands from this cog
                commands_list = []
                
                # Get app commands
                for command in self.bot.tree.get_commands():
                    if hasattr(command, 'callback') and command.callback.__qualname__.startswith(cog.__class__.__name__):
                        # Check if user has permission for this command
                        if cog_name.lower() == "admin" and not is_admin:
                            continue
                        commands_list.append(command)
                
                # Get command groups
                for command in self.bot.tree.get_commands():
                    if isinstance(command, app_commands.Group):
                        if hasattr(command.callback, '__qualname__') and command.callback.__qualname__.startswith(cog.__class__.__name__):
                            if cog_name.lower() == "admin" and not is_admin:
                                continue
                            commands_list.append(command)
                
                if commands_list:
                    available_cogs[cog_name] = {
                        'cog': cog,
                        'commands': commands_list
                    }
            
            if category:
                # Show specific category
                category_title = category.title()
                if category_title not in available_cogs:
                    return await interaction.response.send_message(
                        f"Category '{category}' not found. Available categories: {', '.join(available_cogs.keys())}",
                        ephemeral=True
                    )
                
                embed = discord.Embed(
                    title=f"Help: {category_title}",
                    description=available_cogs[category_title]['cog'].__doc__ or "No description available.",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                
                # Add commands for this category
                commands_text = []
                for cmd in available_cogs[category_title]['commands']:
                    if isinstance(cmd, app_commands.Group):
                        # Show group commands
                        group_commands = [f"  ├─ {subcmd.name}" for subcmd in cmd.commands]
                        commands_text.append(f"**/{cmd.name}** - {cmd.description}")
                        commands_text.extend(group_commands)
                    else:
                        commands_text.append(f"**/{cmd.name}** - {cmd.description}")
                
                if commands_text:
                    embed.add_field(
                        name="Available Commands",
                        value="\n".join(commands_text),
                        inline=False
                    )
                
            else:
                # Show overview of all categories
                embed = discord.Embed(
                    title="Help - Command Categories",
                    description="Here are all available command categories. Use `/help <category>` for detailed information.",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                
                for cog_name, cog_info in available_cogs.items():
                    command_count = len(cog_info['commands'])
                    embed.add_field(
                        name=f"📁 {cog_name}",
                        value=f"{cog_info['cog'].__doc__ or 'No description'}\n`{command_count} command(s)`",
                        inline=True
                    )
                
                # Add general bot info
                embed.add_field(
                    name="ℹ️ About",
                    value=(
                        f"Bot: {self.bot.user.mention}\n"
                        f"Prefix: `/` (slash commands)\n"
                        f"Features can be enabled/disabled per server"
                    ),
                    inline=False
                )
            
            embed.set_footer(text=f"Requested by {interaction.user.display_name}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await interaction.response.send_message(
                "An error occurred while getting help information.",
                ephemeral=True
            )
    
    @help_command.autocomplete('category')
    async def category_autocomplete(
        self, 
        interaction: discord.Interaction, 
        current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for help categories."""
        is_admin = await self.bot.admin_manager.is_bot_admin(interaction.user)
        
        categories = []
        for cog_name in self.bot.cogs.keys():
            if cog_name.startswith('_'):
                continue
            if cog_name.lower() == "admin" and not is_admin:
                continue
            categories.append(cog_name)
        
        return [
            app_commands.Choice(name=category, value=category.lower())
            for category in categories
            if current.lower() in category.lower()
        ][:25]


async def setup(bot):
    await bot.add_cog(Help(bot))