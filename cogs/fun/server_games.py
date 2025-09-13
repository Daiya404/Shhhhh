# cogs/fun/server_games.py
import discord
from discord.ext import commands
from discord import app_commands, ButtonStyle
from discord.ui import View, Button, Modal, TextInput
import logging
import random
from typing import Dict, List, Literal, Optional

from config.personalities import PERSONALITY_RESPONSES
from cogs.admin.bot_admin import is_bot_admin

# --- Word/Art Assets for Hangman (self-contained) ---
HANGMAN_WORDS = ["algorithm", "binary", "boolean", "cache", "compiler", "database", "debug", "encryption", "firewall", "function", "hardware", "interface", "javascript", "keyboard", "loop", "malware", "network", "object", "pixel", "protocol", "python", "query", "recursive", "router", "server", "software", "storage", "syntax", "variable", "virtual", "anime", "manga", "character", "senpai", "waifu", "isekai", "shonen", "shojo", "tsundere", "yandere"]
HANGMAN_PICS = ['```\n +---+\n |   |\n     |\n     |\n     |\n     |\n=========\n```', '```\n +---+\n |   |\n O   |\n     |\n     |\n     |\n=========\n```', '```\n +---+\n |   |\n O   |\n |   |\n     |\n     |\n=========\n```', '```\n +---+\n |   |\n O   |\n/|   |\n     |\n     |\n=========\n```', '```\n +---+\n |   |\n O   |\n/|\\  |\n     |\n     |\n=========\n```', '```\n +---+\n |   |\n O   |\n/|\\  |\n/    |\n     |\n=========\n```', '```\n +---+\n |   |\n O   |\n/|\\  |\n/ \\  |\n     |\n=========\n```']

# --- Helper Classes (Views, Modals, Buttons for all games) ---

class ChallengeView(View):
    def __init__(self, opponent: discord.Member):
        super().__init__(timeout=60)
        self.opponent = opponent
        self.accepted: Optional[bool] = None
    
    @discord.ui.button(label="Accept", style=ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.opponent: 
            return await interaction.response.send_message("This isn't your challenge.", ephemeral=True)
        self.accepted = True
        self.stop()
    
    @discord.ui.button(label="Decline", style=ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.opponent: 
            return await interaction.response.send_message("This isn't your challenge.", ephemeral=True)
        self.accepted = False
        self.stop()

class HangmanLetterModal(Modal, title="Guess a Letter"):
    letter_input = TextInput(label="Enter a single letter (A-Z)", min_length=1, max_length=1, required=True)
    
    def __init__(self, hangman_view):
        super().__init__()
        self.hangman_view = hangman_view
    
    async def on_submit(self, interaction: discord.Interaction):
        letter = self.letter_input.value.lower().strip()
        if not letter.isalpha():
            return await interaction.response.send_message(self.hangman_view.game_cog.personality["hangman_invalid"], ephemeral=True)
        await self.hangman_view.handle_guess(interaction, letter)

class HangmanView(View):
    def __init__(self, game_cog, player: discord.Member, word: str):
        super().__init__(timeout=300)
        self.game_cog = game_cog
        self.player = player
        self.word = word
        self.guessed_letters = set()
        self.wrong_guesses = 0
        self.max_lives = len(HANGMAN_PICS) - 1
        self.message: Optional[discord.Message] = None
    
    async def handle_guess(self, interaction: discord.Interaction, letter: str):
        if letter in self.guessed_letters:
            return await interaction.response.send_message(self.game_cog.personality["hangman_already_guessed"], ephemeral=True)
        
        self.guessed_letters.add(letter)
        if letter not in self.word:
            self.wrong_guesses += 1
        
        embed = self._create_embed()
        if "_" not in self._get_display_word():
            embed.title = self.game_cog.personality["hangman_win"].format(word=self.word.upper())
            embed.color = discord.Color.green()
            self.stop()
        elif self.wrong_guesses >= self.max_lives:
            embed.title = self.game_cog.personality["hangman_lose"].format(word=self.word.upper())
            embed.color = discord.Color.red()
            self.stop()
        
        await interaction.response.edit_message(embed=embed, view=self)

    def _get_display_word(self) -> str:
        return " ".join([letter if letter in self.guessed_letters else "_" for letter in self.word])

    def _create_embed(self) -> discord.Embed:
        embed = discord.Embed(title="Playing Hangman!", color=discord.Color.blue())
        embed.description = f"{HANGMAN_PICS[self.wrong_guesses]}\n\n`{self._get_display_word()}`"
        return embed

    @discord.ui.button(label="Guess Letter", style=ButtonStyle.primary)
    async def guess_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.player: 
            return await interaction.response.send_message("This isn't your game.", ephemeral=True)
        await interaction.response.send_modal(HangmanLetterModal(self))

    async def on_stop(self):
        for item in self.children: 
            item.disabled = True
        if self.message: 
            try: 
                await self.message.edit(view=self)
            except discord.NotFound: 
                pass
        await self.game_cog._cleanup_game(self.player.guild.id, [self.player])

class TicTacToeButton(Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=ButtonStyle.secondary, label="\u200b", row=y)
        self.x, self.y = x, y
    
    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_move(interaction, self.x, self.y)

class TicTacToeView(View):
    def __init__(self, game_cog, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=300)
        self.game_cog, self.players, self.turn = game_cog, [player1, player2], player1
        self.winner: Optional[discord.Member] = None
        self.message: Optional[discord.Message] = None
        self.board = [[" " for _ in range(3)] for _ in range(3)]
        self._update_board()

    def _update_board(self):
        self.clear_items()
        for y in range(3):
            for x in range(3):
                button = TicTacToeButton(x, y)
                if self.board[y][x] == "X": 
                    button.label, button.style = "❌", ButtonStyle.danger
                elif self.board[y][x] == "O": 
                    button.label, button.style = "⭕", ButtonStyle.success
                if self.winner or self.board[y][x] != " ": 
                    button.disabled = True
                self.add_item(button)
        
        resign_button = Button(label="Resign", style=ButtonStyle.danger, row=3, disabled=bool(self.winner))
        resign_button.callback = self.resign_callback
        self.add_item(resign_button)
    
    async def handle_move(self, interaction: discord.Interaction, x: int, y: int):
        if interaction.user != self.turn: 
            return await interaction.response.send_message(self.game_cog.personality["not_your_turn"], ephemeral=True)
        if self.board[y][x] != " ": 
            return await interaction.response.send_message(self.game_cog.personality["invalid_move"], ephemeral=True)
        
        self.board[y][x] = "X" if self.turn == self.players[0] else "O"
        embed = interaction.message.embeds[0]
        
        if self._check_win():
            self.winner = self.turn
            loser = self.players[1] if self.winner == self.players[0] else self.players[0]
            embed.description = self.game_cog.personality["win_message"].format(winner=self.winner.mention, loser=loser.mention)
            self.stop()
        elif all(cell != " " for row in self.board for cell in row):
            embed.description = self.game_cog.personality["draw_message"]
            self.stop()
        else:
            self.turn = self.players[1] if self.turn == self.players[0] else self.players[0]
            embed.description = f"It's **{self.turn.mention}'s** turn."
        
        self._update_board()
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def resign_callback(self, interaction: discord.Interaction):
        if interaction.user not in self.players: 
            return await interaction.response.send_message("This isn't your game.", ephemeral=True)
        
        self.winner = self.players[1] if interaction.user == self.players[0] else self.players[0]
        embed = interaction.message.embeds[0]
        embed.description = self.game_cog.personality["game_resigned"].format(player=interaction.user.mention, winner=self.winner.mention)
        self._update_board()
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    def _check_win(self) -> bool:
        lines = self.board + [[self.board[i][j] for i in range(3)] for j in range(3)] + [[self.board[i][i] for i in range(3)], [self.board[i][2-i] for i in range(3)]]
        return any(line[0] == line[1] == line[2] != " " for line in lines)
    
    async def on_stop(self):
        for item in self.children: 
            item.disabled = True
        if self.message: 
            try: 
                await self.message.edit(view=self)
            except discord.NotFound: 
                pass
        await self.game_cog._cleanup_game(self.players[0].guild.id, self.players)

class Connect4Button(Button):
    def __init__(self, column: int, **kwargs):
        super().__init__(**kwargs)
        self.column = column
    
    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_move(interaction, self.column)

class Connect4View(View):
    def __init__(self, game_cog, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=300)
        self.game_cog, self.players, self.turn = game_cog, [player1, player2], player1
        self.winner: Optional[discord.Member] = None
        self.message: Optional[discord.Message] = None
        self.board = [[" " for _ in range(7)] for _ in range(6)]
        self._update_board()

    def _update_board(self):
        self.clear_items()
        
        # Row 0: Columns 1-3
        for i in range(3):
            button = Connect4Button(column=i, label=str(i + 1), style=ButtonStyle.secondary, row=0)
            # Disable button if the column is full or game is over
            if self.board[0][i] != " " or self.winner:
                button.disabled = True
            self.add_item(button)
        
        # Row 1: Columns 4-6
        for i in range(3, 6):
            button = Connect4Button(column=i, label=str(i + 1), style=ButtonStyle.secondary, row=1)
            # Disable button if the column is full or game is over
            if self.board[0][i] != " " or self.winner:
                button.disabled = True
            self.add_item(button)
        
        # Row 2: Player indicators and Column 7
        # Red button (Player 1 indicator)
        red_style = ButtonStyle.primary if self.turn == self.players[0] and not self.winner else ButtonStyle.secondary
        red_button = Button(label="🔴", style=red_style, row=2, disabled=True)
        self.add_item(red_button)
        
        # Column 7 button
        button = Connect4Button(column=6, label="7", style=ButtonStyle.secondary, row=2)
        if self.board[0][6] != " " or self.winner:
            button.disabled = True
        self.add_item(button)
        
        # Yellow button (Player 2 indicator)  
        yellow_style = ButtonStyle.primary if self.turn == self.players[1] and not self.winner else ButtonStyle.secondary
        yellow_button = Button(label="🟡", style=yellow_style, row=2, disabled=True)
        self.add_item(yellow_button)
        
        # Row 3: Resign button
        resign_button = Button(label="Resign", style=ButtonStyle.danger, row=3, disabled=bool(self.winner))
        resign_button.callback = self.resign_callback
        self.add_item(resign_button)

    def get_board_string(self) -> str:
        emoji_map = {" ": "⚫", "X": "🔴", "O": "🟡"}
        board_str = "\n".join("".join(emoji_map[cell] for cell in row) for row in self.board)
        # Add column numbers at the bottom
        column_numbers = "1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣"
        return f"{board_str}\n{column_numbers}"

    async def handle_move(self, interaction: discord.Interaction, column: int):
        if interaction.user != self.turn: 
            return await interaction.response.send_message(self.game_cog.personality["not_your_turn"], ephemeral=True)
        
        for row in range(5, -1, -1):
            if self.board[row][column] == " ":
                self.board[row][column] = "X" if self.turn == self.players[0] else "O"
                break
        else:
            return await interaction.response.send_message(self.game_cog.personality["invalid_move"], ephemeral=True)

        embed = interaction.message.embeds[0]
        
        if self._check_win():
            self.winner = self.turn
            loser = self.players[1] if self.winner == self.players[0] else self.players[0]
            embed.description = f"{self.get_board_string()}\n\n{self.game_cog.personality['win_message'].format(winner=self.winner.mention, loser=loser.mention)}"
            self.stop()
        elif all(self.board[0][i] != " " for i in range(7)):
            embed.description = f"{self.get_board_string()}\n\n{self.game_cog.personality['draw_message']}"
            self.stop()
        else:
            self.turn = self.players[1] if self.turn == self.players[0] else self.players[0]
            embed.description = f"{self.get_board_string()}\n\nIt's **{self.turn.mention}'s** turn."
        
        self._update_board()
        await interaction.response.edit_message(embed=embed, view=self)
        
    async def resign_callback(self, interaction: discord.Interaction):
        if interaction.user not in self.players: 
            return await interaction.response.send_message("This isn't your game.", ephemeral=True)
        
        self.winner = self.players[1] if interaction.user == self.players[0] else self.players[0]
        embed = interaction.message.embeds[0]
        embed.description = f"{self.get_board_string()}\n\n{self.game_cog.personality['game_resigned'].format(player=interaction.user.mention, winner=self.winner.mention)}"
        self._update_board()
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    def _check_win(self) -> bool:
        for y in range(6):
            for x in range(7):
                if self.board[y][x] == " ": 
                    continue
                # Horizontal, Vertical, and Diagonal checks
                if x <= 3 and all(self.board[y][x+i] == self.board[y][x] for i in range(4)): 
                    return True
                if y <= 2 and all(self.board[y+i][x] == self.board[y][x] for i in range(4)): 
                    return True
                if x <= 3 and y <= 2 and all(self.board[y+i][x+i] == self.board[y][x] for i in range(4)): 
                    return True
                if x >= 3 and y <= 2 and all(self.board[y+i][x-i] == self.board[y][x] for i in range(4)): 
                    return True
        return False

    async def on_stop(self):
        for item in self.children: 
            item.disabled = True
        if self.message:
            try: 
                await self.message.edit(view=self)
            except discord.NotFound: 
                pass
        await self.game_cog._cleanup_game(self.players[0].guild.id, self.players)

class ServerGames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.personality = PERSONALITY_RESPONSES["server_games"]
        self.data_manager = self.bot.data_manager
        self.active_games_cache: Dict[str, Dict[str, str]] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info("Loading active games into memory...")
        self.active_games_cache = await self.data_manager.get_data("active_server_games")
        self.logger.info("Active games cache is ready.")

    async def _cleanup_game(self, guild_id: int, players: List[discord.Member]):
        guild_games = self.active_games_cache.get(str(guild_id), {})
        if not guild_games: 
            return
        
        cleaned = any(guild_games.pop(str(player.id), None) for player in players)
        if cleaned:
            await self.data_manager.save_data("active_server_games", self.active_games_cache)

    async def _check_and_clear_stuck_players(self, guild_id: int, *player_ids: int) -> bool:
        """Check if players are stuck in games and clear them if so. Returns True if any were cleared."""
        guild_games = self.active_games_cache.get(str(guild_id), {})
        if not guild_games:
            return False
        
        cleared_any = False
        for player_id in player_ids:
            if str(player_id) in guild_games:
                self.logger.warning(f"Found stuck player {player_id} in game state, clearing...")
                del guild_games[str(player_id)]
                cleared_any = True
        
        if cleared_any:
            await self.data_manager.save_data("active_server_games", self.active_games_cache)
            
        return cleared_any

    async def _start_challenge(self, interaction: discord.Interaction, opponent: discord.Member, game_type: Literal["tictactoe", "connect4"]):
        challenger = interaction.user
        if challenger.id == opponent.id: 
            return await interaction.response.send_message(self.personality["self_challenge"], ephemeral=True)
        if opponent.bot: 
            return await interaction.response.send_message(self.personality["bot_challenge"], ephemeral=True)
        
        # Check and clear any stuck players before proceeding
        await self._check_and_clear_stuck_players(interaction.guild_id, challenger.id, opponent.id)
        
        guild_games = self.active_games_cache.get(str(interaction.guild_id), {})
        if str(challenger.id) in guild_games: 
            return await interaction.response.send_message(self.personality["game_already_running"], ephemeral=True)
        if str(opponent.id) in guild_games: 
            return await interaction.response.send_message(self.personality["opponent_in_game"], ephemeral=True)
        
        game_name = "Tic-Tac-Toe" if game_type == "tictactoe" else "Connect 4"
        view = ChallengeView(opponent)
        await interaction.response.send_message(self.personality["challenge_sent"].format(challenger=challenger.mention, opponent=opponent.mention, game_name=game_name), view=view)
        await view.wait()
        
        original_message = await interaction.original_response()
        
        if view.accepted:
            guild_games = self.active_games_cache.setdefault(str(interaction.guild_id), {})
            guild_games[str(challenger.id)] = game_type
            guild_games[str(opponent.id)] = game_type
            await self.data_manager.save_data("active_server_games", self.active_games_cache)
            
            if game_type == "tictactoe":
                game_view = TicTacToeView(self, challenger, opponent)
                embed = discord.Embed(title=f"Playing {game_name}!", description=f"It's **{challenger.mention}'s** turn.", color=discord.Color.blue())
            else: # Connect 4
                game_view = Connect4View(self, challenger, opponent)
                embed = discord.Embed(title=f"Playing {game_name}!", description=f"{game_view.get_board_string()}\n\nIt's **{challenger.mention}'s** turn.", color=discord.Color.blue())

            await original_message.edit(content=None, embed=embed, view=game_view)
            game_view.message = original_message
        elif view.accepted is False:
            await original_message.edit(content=self.personality["challenge_declined"].format(opponent=opponent.mention), view=None)
        else:
            await original_message.edit(content=self.personality["challenge_timeout"].format(opponent=opponent.mention), view=None)

    @app_commands.command(name="play", description="Play a game - choose from Hangman, Tic-Tac-Toe, or Connect 4.")
    @app_commands.describe(
        game="The game you want to play",
        opponent="The opponent for multiplayer games (not needed for Hangman)"
    )
    @app_commands.choices(game=[
        app_commands.Choice(name="Hangman (Single Player)", value="hangman"),
        app_commands.Choice(name="Tic-Tac-Toe", value="tictactoe"),
        app_commands.Choice(name="Connect 4", value="connect4")
    ])
    async def play(self, interaction: discord.Interaction, game: str, opponent: Optional[discord.Member] = None):
        if game == "hangman":
            await self._start_hangman(interaction)
        elif game in ["tictactoe", "connect4"]:
            if not opponent:
                return await interaction.response.send_message(f"You need to specify an opponent for {game.replace('_', '-').title()}.", ephemeral=True)
            await self._start_challenge(interaction, opponent, game)
        else:
            await interaction.response.send_message("Invalid game choice.", ephemeral=True)

    async def _start_hangman(self, interaction: discord.Interaction):
        await interaction.response.defer()
        player = interaction.user
        
        # Check and clear stuck players
        await self._check_and_clear_stuck_players(interaction.guild_id, player.id)
        
        guild_games = self.active_games_cache.get(str(interaction.guild_id), {})
        if str(player.id) in guild_games: 
            return await interaction.followup.send(self.personality["game_already_running"], ephemeral=True)
        
        guild_games = self.active_games_cache.setdefault(str(interaction.guild_id), {})
        guild_games[str(player.id)] = "hangman"
        await self.data_manager.save_data("active_server_games", self.active_games_cache)
        
        word = random.choice(HANGMAN_WORDS)
        view = HangmanView(self, player, word)
        embed = view._create_embed()
        embed.set_footer(text=self.personality["hangman_start"].format(lives=view.max_lives))
        await interaction.followup.send(embed=embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="game-admin", description="[Admin] Manage server games.")
    @app_commands.default_permissions(manage_messages=True)
    @is_bot_admin()
    @app_commands.describe(action="The action to perform.", user="The user whose game state you want to clear (for 'clear-user').")
    @app_commands.choices(action=[
        app_commands.Choice(name="View Active Games", value="list"), 
        app_commands.Choice(name="Clear User's Game", value="clear-user"), 
        app_commands.Choice(name="Clear All Games", value="clear-all")
    ])
    async def game_admin(self, interaction: discord.Interaction, action: str, user: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id)
        guild_games = self.active_games_cache.get(guild_id_str, {})
        
        if action == "list":
            if not guild_games: 
                return await interaction.followup.send("There are no active games in this server.")
            embed = discord.Embed(title="Active Server Games", color=discord.Color.blue(), description="\n".join([f"<@{uid}> is playing **{game_type}**" for uid, game_type in guild_games.items()]))
            await interaction.followup.send(embed=embed)
        elif action == "clear-user":
            if not user: 
                return await interaction.followup.send("You must specify a user to clear.")
            if guild_games.pop(str(user.id), None):
                await self.data_manager.save_data("active_server_games", self.active_games_cache)
                await interaction.followup.send(f"Cleared the game state for **{user.display_name}**.")
            else:
                await interaction.followup.send(f"**{user.display_name}** is not in an active game.")
        elif action == "clear-all":
            if not guild_games: 
                return await interaction.followup.send("There were no active games to clear.")
            count = len(guild_games)
            self.active_games_cache.pop(guild_id_str, None)
            await self.data_manager.save_data("active_server_games", self.active_games_cache)
            await interaction.followup.send(f"Cleared **{count}** active game(s) for this server.")

async def setup(bot):
    await bot.add_cog(ServerGames(bot))