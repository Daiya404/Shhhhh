import discord
from discord.ext import commands
from discord import app_commands, ButtonStyle
from discord.ui import View, Button, Modal, TextInput
import logging
import random
from typing import Dict, List, Literal, Optional
import asyncio

from .bot_admin import BotAdmin

# --- Personality (Unchanged) ---
PERSONALITY = {
    "challenge_sent": "Hmph. {challenger} has challenged {opponent} to a game of **{game_name}**. Are you going to accept, {opponent}, or are you scared?",
    "challenge_accepted": "Fine, the game is on. It's **{player}'s** turn to move.",
    "challenge_declined": "Looks like {opponent} was too scared to play. How predictable.",
    "challenge_timeout": "Well, {opponent} didn't respond. I guess we have our answer.",
    "game_already_running": "You're already in a game. Finish it before you start another one.",
    "opponent_in_game": "They're already busy with another game. Find someone else to bother.",
    "not_your_turn": "It's not your turn. Don't be so impatient.",
    "invalid_move": "You can't play there. Are you even paying attention to the board?",
    "win_message": "The game is over. **{winner}** won. I guess that makes you the loser, {loser}.",
    "draw_message": "A draw. How utterly boring. Neither of you could win.",
    "game_timeout": "The game timed out because someone took too long. Pathetic.",
    "game_resigned": "**{player}** resigned from the game. How disappointing. **{winner}** wins by default.",
    "hangman_start": "Alright, I've thought of a word. Start guessing letters by typing them. You have {lives} wrong guesses before you lose.",
    "hangman_win": "You actually guessed it. The word was **{word}**. I'm impressed... for once.",
    "hangman_lose": "You lose. How disappointing. The word was **{word}**.",
    "hangman_already_guessed": "You already guessed that letter. Try to keep up.",
    "hangman_invalid": "That's not a valid letter. Try again.",
    "not_in_game": "You're not in any game to resign from."
}

# --- Word List for Hangman ---
HANGMAN_WORDS = [
    "algorithm", "binary", "boolean", "cache", "compiler", "database", "debug", "encryption",
    "firewall", "function", "hardware", "interface", "javascript", "keyboard", "loop", "malware",
    "network", "object", "pixel", "protocol", "python", "query", "recursive", "router", "server",
    "software", "storage", "syntax", "variable", "virtual", "anime", "manga", "character", "senpai",
    "waifu", "isekai", "shonen", "shojo", "tsundere", "yandere"
]

# --- ASCII Art for Hangman ---
HANGMAN_PICS = [
    '```\n +---+\n |   |\n     |\n     |\n     |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n     |\n     |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n |   |\n     |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n/|   |\n     |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n/|\\  |\n     |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n/|\\  |\n/    |\n     |\n=========\n```',
    '```\n +---+\n |   |\n O   |\n/|\\  |\n/ \\  |\n     |\n=========\n```'
]

# --- NEW HANGMAN CLASSES ---
class HangmanLetterModal(Modal):
    def __init__(self, hangman_view):
        super().__init__(title="Guess a Letter")
        self.hangman_view = hangman_view
        
        self.letter_input = TextInput(
            label="Enter a letter:",
            placeholder="Type a single letter (A-Z)",
            max_length=1,
            min_length=1,
            required=True
        )
        self.add_item(self.letter_input)

    async def on_submit(self, interaction: discord.Interaction):
        letter = self.letter_input.value.lower().strip()
        
        if not letter.isalpha():
            return await interaction.response.send_message(PERSONALITY["hangman_invalid"], ephemeral=True)
        
        await self.hangman_view.handle_guess(interaction, letter)

class HangmanView(View):
    def __init__(self, game_cog, player: discord.Member):
        super().__init__(timeout=300)
        self.game_cog = game_cog
        self.player = player
        self.word = random.choice(HANGMAN_WORDS).lower()
        self.guessed_letters = set()
        self.wrong_guesses = 0
        self.max_lives = len(HANGMAN_PICS) - 1
        self.message: Optional[discord.Message] = None
        self.winner = None
        self.game_ended = False

        self.create_buttons()

    def create_buttons(self):
        self.clear_items()
        
        # Guess Letter button
        guess_button = Button(label="Guess Letter", style=ButtonStyle.primary, disabled=self.game_ended)
        guess_button.callback = self.guess_letter_callback
        self.add_item(guess_button)
        
        # Resign button
        resign_button = Button(label="Resign", style=ButtonStyle.danger, disabled=self.game_ended)
        resign_button.callback = self.resign_callback
        self.add_item(resign_button)

    async def guess_letter_callback(self, interaction: discord.Interaction):
        if interaction.user != self.player:
            return await interaction.response.send_message("This isn't your game.", ephemeral=True)
        if self.game_ended:
            return await interaction.response.send_message("The game has already ended.", ephemeral=True)
        
        modal = HangmanLetterModal(self)
        await interaction.response.send_modal(modal)

    async def resign_callback(self, interaction: discord.Interaction):
        if interaction.user != self.player:
            return await interaction.response.send_message("This isn't your game.", ephemeral=True)
        if self.game_ended:
            return await interaction.response.send_message("The game has already ended.", ephemeral=True)
        
        self.winner = False
        self.game_ended = True
        embed = self.message.embeds[0]
        embed.title = f"Game Resigned - The word was **{self.word.upper()}**"
        embed.description = f"{HANGMAN_PICS[-1]}\n\n`{self.word.upper()}`"
        embed.color = discord.Color.red()
        self.create_buttons()
        
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    def get_display_word(self) -> str:
        """Returns the word with unguessed letters as underscores."""
        return " ".join([letter if letter in self.guessed_letters else "_" for letter in self.word])

    def get_guessed_letters_display(self) -> str:
        """Returns a formatted string of guessed letters."""
        if not self.guessed_letters:
            return "None"
        correct = [l.upper() for l in self.guessed_letters if l in self.word]
        wrong = [l.upper() for l in self.guessed_letters if l not in self.word]
        result = ""
        if correct:
            result += f"✅ {', '.join(sorted(correct))}"
        if wrong:
            if correct:
                result += " | "
            result += f"❌ {', '.join(sorted(wrong))}"
        return result

    async def handle_guess(self, interaction: discord.Interaction, letter: str):
        if letter in self.guessed_letters:
            return await interaction.response.send_message(PERSONALITY["hangman_already_guessed"], ephemeral=True)
        
        self.guessed_letters.add(letter)
        
        if letter not in self.word:
            self.wrong_guesses += 1

        display_word = self.get_display_word()
        guessed_display = self.get_guessed_letters_display()
        
        embed = self.message.embeds[0]
        embed.description = f"{HANGMAN_PICS[self.wrong_guesses]}\n\n`{display_word}`\n\n**Guessed:** {guessed_display}"

        # Check for win/loss
        if "_" not in display_word:
            self.winner = True
            self.game_ended = True
            embed.color = discord.Color.green()
            embed.title = PERSONALITY["hangman_win"].format(word=self.word.upper())
            self.stop()
        elif self.wrong_guesses >= self.max_lives:
            self.winner = False
            self.game_ended = True
            embed.color = discord.Color.red()
            embed.title = PERSONALITY["hangman_lose"].format(word=self.word.upper())
            self.stop()

        self.create_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.game_ended:
            return
        self.game_ended = True
        self.winner = "Timeout"
        embed = self.message.embeds[0] if self.message and self.message.embeds else discord.Embed()
        embed.title = "Game timed out."
        embed.description = f"{HANGMAN_PICS[-1]}\n\nThe word was **{self.word.upper()}**."
        embed.color = discord.Color.orange()
        self.create_buttons()
        try: 
            await self.message.edit(embed=embed, view=self)
        except (discord.NotFound, discord.HTTPException):
            pass
        self.stop()

    async def on_stop(self):
        if not self.game_ended:
            self.game_ended = True
        try:
            self.game_cog._cleanup_game([self.player])
        except Exception as e:
            self.game_cog.logger.error(f"Error in hangman cleanup: {e}")
            # Force cleanup as fallback
            self.game_cog.active_games.pop(self.player.id, None)

# --- TicTacToe Classes ---
class TicTacToeButton(Button):
    def __init__(self, x: int, y: int, **kwargs):
        super().__init__(**kwargs)
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
        self.game_ended = False
        self.create_board()
    
    def create_board(self):
        self.clear_items()
        for y in range(3):
            for x in range(3):
                label, style = "\u200b", ButtonStyle.secondary
                if self.board[y][x] == "X": 
                    label, style = "❌", ButtonStyle.danger
                elif self.board[y][x] == "O": 
                    label, style = "⭕", ButtonStyle.success
                button = TicTacToeButton(x=x, y=y, label=label, style=style, row=y)
                if self.game_ended or self.board[y][x] != " ": 
                    button.disabled = True
                self.add_item(button)
        
        # Add resign button
        resign_button = Button(label="Resign", style=ButtonStyle.danger, row=3, disabled=self.game_ended)
        resign_button.callback = self.resign_callback
        self.add_item(resign_button)

    async def resign_callback(self, interaction: discord.Interaction):
        if interaction.user not in self.players:
            return await interaction.response.send_message("This isn't your game.", ephemeral=True)
        if self.game_ended:
            return await interaction.response.send_message("The game has already ended.", ephemeral=True)
        
        resigning_player = interaction.user
        winner = self.players[1] if resigning_player == self.players[0] else self.players[0]
        
        self.winner = winner
        self.game_ended = True
        embed = interaction.message.embeds[0]
        embed.description = PERSONALITY["game_resigned"].format(player=resigning_player.mention, winner=winner.mention)
        embed.color = discord.Color.orange()
        self.create_board()
        
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def handle_move(self, interaction: discord.Interaction, x: int, y: int):
        if interaction.user != self.turn: 
            return await interaction.response.send_message(PERSONALITY["not_your_turn"], ephemeral=True)
        if self.game_ended or self.board[y][x] != " ": 
            return await interaction.response.send_message(PERSONALITY["invalid_move"], ephemeral=True)
        
        self.board[y][x] = "X" if self.turn == self.players[0] else "O"
        win_result = self.check_for_win()
        embed = interaction.message.embeds[0]
        
        if win_result:
            self.winner = win_result
            self.game_ended = True
            loser = self.players[1] if self.winner == self.players[0] else self.players[0]
            embed.description = PERSONALITY["win_message"].format(winner=self.winner.mention, loser=loser.mention)
            embed.color = discord.Color.green()
            self.stop()
        elif all(cell != " " for row in self.board for cell in row):
            self.game_ended = True
            embed.description = PERSONALITY["draw_message"]
            embed.color = discord.Color.orange()
            self.winner = "Draw"
            self.stop()
        else:
            self.turn = self.players[1] if self.turn == self.players[0] else self.players[0]
            embed.description = f"It's **{self.turn.mention}'s** turn."
        
        self.create_board()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.game_ended:
            return
        self.game_ended = True
        self.winner = "Timeout"
        if self.message and self.message.embeds:
            embed = self.message.embeds[0]
            embed.description = PERSONALITY["game_timeout"]
            embed.color = discord.Color.red()
            self.create_board()
            try: 
                await self.message.edit(embed=embed, view=self)
            except (discord.NotFound, discord.HTTPException): 
                pass
        self.stop()

    async def on_stop(self): 
        if not self.game_ended:
            self.game_ended = True
        try:
            self.game_cog._cleanup_game(self.players)
        except Exception as e:
            self.game_cog.logger.error(f"Error in tictactoe cleanup: {e}")
            # Force cleanup as fallback
            for player in self.players:
                self.game_cog.active_games.pop(player.id, None)

    def check_for_win(self) -> Optional[discord.Member]:
        lines = (
            self.board[0], self.board[1], self.board[2], 
            [self.board[i][0] for i in range(3)], 
            [self.board[i][1] for i in range(3)], 
            [self.board[i][2] for i in range(3)], 
            [self.board[i][i] for i in range(3)], 
            [self.board[i][2-i] for i in range(3)]
        )
        for line in lines:
            if line[0] == line[1] == line[2] != " ":
                return self.players[0] if line[0] == "X" else self.players[1]
        return None

# --- Connect4 Classes ---
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
        self.game_ended = False
        self.create_buttons()

    def create_buttons(self):
        self.clear_items()
        
        # Row 1: Columns 1-3
        for i in range(3):
            button = Connect4Button(column=i, label=str(i+1), style=ButtonStyle.secondary, row=0)
            if self.game_ended or self.board[0][i] != " ": 
                button.disabled = True
            self.add_item(button)
        
        # Row 2: Columns 4-6
        for i in range(3, 6):
            button = Connect4Button(column=i, label=str(i+1), style=ButtonStyle.secondary, row=1)
            if self.game_ended or self.board[0][i] != " ": 
                button.disabled = True
            self.add_item(button)
        
        # Row 3: Yellow, Column 7, Red
        # Yellow button (Player 2 - O)
        yellow_style = ButtonStyle.primary if self.turn == self.players[1] and not self.game_ended else ButtonStyle.secondary
        yellow_button = Button(label="🟡", style=yellow_style, row=2, disabled=True)
        self.add_item(yellow_button)
        
        # Column 7 button
        button = Connect4Button(column=6, label="7", style=ButtonStyle.secondary, row=2)
        if self.game_ended or self.board[0][6] != " ": 
            button.disabled = True
        self.add_item(button)
        
        # Red button (Player 1 - X)
        red_style = ButtonStyle.primary if self.turn == self.players[0] and not self.game_ended else ButtonStyle.secondary
        red_button = Button(label="🔴", style=red_style, row=2, disabled=True)
        self.add_item(red_button)
        
        # Resign button
        resign_button = Button(label="Resign", style=ButtonStyle.danger, row=3, disabled=self.game_ended)
        resign_button.callback = self.resign_callback
        self.add_item(resign_button)

    async def resign_callback(self, interaction: discord.Interaction):
        if interaction.user not in self.players:
            return await interaction.response.send_message("This isn't your game.", ephemeral=True)
        if self.game_ended:
            return await interaction.response.send_message("The game has already ended.", ephemeral=True)
        
        resigning_player = interaction.user
        winner = self.players[1] if resigning_player == self.players[0] else self.players[0]
        
        self.winner = winner
        self.game_ended = True
        embed = interaction.message.embeds[0]
        embed.description = f"{self.get_board_string()}\n\n{PERSONALITY['game_resigned'].format(player=resigning_player.mention, winner=winner.mention)}"
        embed.color = discord.Color.orange()
        self.create_buttons()
        
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    def get_board_string(self) -> str:
        """Creates the text representation of the board with column numbers."""
        emoji_map = {" ": "⚫", "X": "🔴", "O": "🟡"}
        board_str = "\n".join("".join(emoji_map[cell] for cell in row) for row in self.board)
        # Add column numbers at the bottom
        column_numbers = "1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣"
        return f"{board_str}\n{column_numbers}"

    async def handle_move(self, interaction: discord.Interaction, column: int):
        if interaction.user != self.turn: 
            return await interaction.response.send_message(PERSONALITY["not_your_turn"], ephemeral=True)
        if self.game_ended: 
            return await interaction.response.send_message("The game has already ended.", ephemeral=True)

        # Find the lowest available row in the column
        placed = False
        for row in range(5, -1, -1):
            if self.board[row][column] == " ":
                self.board[row][column] = "X" if self.turn == self.players[0] else "O"
                placed = True
                break
        
        if not placed:
            return await interaction.response.send_message(PERSONALITY["invalid_move"], ephemeral=True)

        win_result = self.check_for_win()
        embed = interaction.message.embeds[0]
        
        if win_result:
            self.winner = win_result
            self.game_ended = True
            loser = self.players[1] if self.winner == self.players[0] else self.players[0]
            embed.description = f"{self.get_board_string()}\n\n{PERSONALITY['win_message'].format(winner=self.winner.mention, loser=loser.mention)}"
            embed.color = discord.Color.green()
            self.stop()
        elif all(cell != " " for row in self.board for cell in row):
            self.game_ended = True
            embed.description = f"{self.get_board_string()}\n\n{PERSONALITY['draw_message']}"
            embed.color = discord.Color.orange()
            self.winner = "Draw"
            self.stop()
        else:
            self.turn = self.players[1] if self.turn == self.players[0] else self.players[0]
            embed.description = f"{self.get_board_string()}\n\nIt's **{self.turn.mention}'s** turn."
        
        self.create_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.game_ended:
            return
        self.game_ended = True
        self.winner = "Timeout"
        if self.message and self.message.embeds:
            embed = self.message.embeds[0]
            embed.description = f"{self.get_board_string()}\n\n{PERSONALITY['game_timeout']}"
            embed.color = discord.Color.red()
            self.create_buttons()
            try: 
                await self.message.edit(embed=embed, view=self)
            except (discord.NotFound, discord.HTTPException): 
                pass
        self.stop()
        
    async def on_stop(self): 
        if not self.game_ended:
            self.game_ended = True
        try:
            self.game_cog._cleanup_game(self.players)
        except Exception as e:
            self.game_cog.logger.error(f"Error in connect4 cleanup: {e}")
            # Force cleanup as fallback
            for player in self.players:
                self.game_cog.active_games.pop(player.id, None)

    def check_for_win(self) -> Optional[discord.Member]:
        height, width, win_con = 6, 7, 4
        symbols = ["X", "O"]
        for symbol in symbols:
            player = self.players[symbols.index(symbol)]
            for y in range(height):
                for x in range(width):
                    # Horizontal
                    if x <= width - win_con and all(self.board[y][x+i] == symbol for i in range(win_con)): 
                        return player
                    # Vertical  
                    if y <= height - win_con and all(self.board[y+i][x] == symbol for i in range(win_con)): 
                        return player
                    # Diagonal (down-right)
                    if x <= width - win_con and y <= height - win_con and all(self.board[y+i][x+i] == symbol for i in range(win_con)): 
                        return player
                    # Diagonal (down-left)
                    if x >= win_con - 1 and y <= height - win_con and all(self.board[y+i][x-i] == symbol for i in range(win_con)): 
                        return player
        return None

# --- Main Cog Class ---
class ServerGames(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.active_games: Dict[int, str] = {}

    def _cleanup_game(self, players: List[discord.Member]):
        """Clean up game state for the given players."""
        cleaned_players = []
        for player in players: 
            if player.id in self.active_games:
                del self.active_games[player.id]
                cleaned_players.append(player.id)
        self.logger.info(f"Cleaned up game state for players: {cleaned_players}")
        return len(cleaned_players)

    def _force_cleanup_player(self, player_id: int):
        """Force cleanup for a specific player (useful for debugging)."""
        if player_id in self.active_games:
            del self.active_games[player_id]
            self.logger.info(f"Force cleaned up player {player_id}")
            return True
        return False

    game_group = app_commands.Group(name="game", description="Play a game with another server member.")

    @game_group.command(name="hangman", description="Play a single-player game of Hangman.")
    async def hangman(self, interaction: discord.Interaction):
        player = interaction.user
        
        # Force cleanup if player is stuck (more aggressive approach)
        if self.active_games.get(player.id):
            self.logger.warning(f"Player {player.id} was stuck in game state, force cleaning")
            self._force_cleanup_player(player.id)
        
        self.active_games[player.id] = "hangman"
        self.logger.info(f"Started hangman game for player {player.id}")
        
        view = HangmanView(self, player)
        
        embed = discord.Embed(
            title="Playing Hangman!",
            description=f"{HANGMAN_PICS[0]}\n\n`{view.get_display_word()}`\n\n**Guessed:** None",
            color=discord.Color.blue()
        )
        embed.set_footer(text=PERSONALITY["hangman_start"].format(lives=view.max_lives))

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @game_group.command(name="resign", description="Resign from your current game.")
    async def resign(self, interaction: discord.Interaction):
        player_id = interaction.user.id
        
        if player_id not in self.active_games:
            return await interaction.response.send_message(PERSONALITY["not_in_game"], ephemeral=True)
        
        # For hangman games, we need to handle resignation differently since there's no opponent
        game_type = self.active_games[player_id]
        if game_type == "hangman":
            # For hangman, just clear the game state
            self._force_cleanup_player(player_id)
            return await interaction.response.send_message("You have resigned from your Hangman game.", ephemeral=True)
        
        # For multiplayer games, we can't handle resignation here since we don't have access to the game view
        # The resign functionality is handled within each game's view
        await interaction.response.send_message("Use the 'Resign' button in your active game to resign.", ephemeral=True)

    async def _start_challenge(self, interaction: discord.Interaction, opponent: discord.Member, game_type: Literal["tictactoe", "connect4"]):
        challenger = interaction.user
        
        # Validation checks with auto-cleanup
        if challenger.id == opponent.id: 
            return await interaction.response.send_message("You can't challenge yourself.", ephemeral=True)
        if opponent.bot: 
            return await interaction.response.send_message("You can't challenge a bot.", ephemeral=True)
            
        # More aggressive cleanup approach
        if self.active_games.get(challenger.id): 
            self.logger.warning(f"Challenger {challenger.id} was stuck in game state, force cleaning")
            self._force_cleanup_player(challenger.id)
            
        if self.active_games.get(opponent.id): 
            self.logger.warning(f"Opponent {opponent.id} was stuck in game state, force cleaning")  
            self._force_cleanup_player(opponent.id)

        game_name = "Tic-Tac-Toe" if game_type == "tictactoe" else "Connect 4"
        
        class ChallengeView(View):
            def __init__(self, timeout=60): 
                super().__init__(timeout=timeout)
                self.accepted = None
                
            @discord.ui.button(label="Accept", style=ButtonStyle.success)
            async def accept(self, i: discord.Interaction, b: Button):
                if i.user != opponent: 
                    return await i.response.send_message("This isn't your challenge.", ephemeral=True)
                await i.response.defer()
                self.accepted = True
                self.stop()
                
            @discord.ui.button(label="Decline", style=ButtonStyle.danger)
            async def decline(self, i: discord.Interaction, b: Button):
                if i.user != opponent: 
                    return await i.response.send_message("This isn't your challenge.", ephemeral=True)
                await i.response.defer()
                self.accepted = False
                self.stop()

        challenge_view = ChallengeView()
        challenge_message = PERSONALITY["challenge_sent"].format(
            challenger=challenger.mention, 
            opponent=opponent.mention, 
            game_name=game_name
        )
        
        await interaction.response.send_message(challenge_message, view=challenge_view)
        
        await challenge_view.wait()
        original_message = await interaction.original_response()

        if challenge_view.accepted is True:
            # Mark both players as in-game
            self.active_games[challenger.id] = game_type
            self.active_games[opponent.id] = game_type
            self.logger.info(f"Started {game_type} game between {challenger.id} and {opponent.id}")
            
            if game_type == "tictactoe":
                game_view = TicTacToeView(self, challenger, opponent)
                embed = discord.Embed(
                    title="Playing Tic-Tac-Toe!", 
                    description=PERSONALITY["challenge_accepted"].format(player=challenger.mention), 
                    color=discord.Color.blue()
                )
            else:  # Connect 4
                game_view = Connect4View(self, challenger, opponent)
                embed = discord.Embed(title="Playing Connect 4!", color=discord.Color.blue())
                embed.description = f"{game_view.get_board_string()}\n\n{PERSONALITY['challenge_accepted'].format(player=challenger.mention)}"

            await original_message.edit(content=None, embed=embed, view=game_view)
            game_view.message = original_message
            
        elif challenge_view.accepted is False:
            await original_message.edit(content=PERSONALITY["challenge_declined"].format(opponent=opponent.mention), view=None)
        else:
            await original_message.edit(content=PERSONALITY["challenge_timeout"].format(opponent=opponent.mention), view=None)

    @game_group.command(name="tictactoe", description="Challenge someone to a game of Tic-Tac-Toe.")
    @app_commands.describe(opponent="The user you want to play against.")
    async def tictactoe(self, interaction: discord.Interaction, opponent: discord.Member):
        await self._start_challenge(interaction, opponent, "tictactoe")
        
    @game_group.command(name="connect4", description="Challenge someone to a game of Connect 4.")
    @app_commands.describe(opponent="The user you want to play against.")
    async def connect4(self, interaction: discord.Interaction, opponent: discord.Member):
        await self._start_challenge(interaction, opponent, "connect4")

    # Add commands to check and manage game states
    @app_commands.command(name="cleargame", description="[DEBUG] Force clear your game status if stuck.")
    async def clear_game(self, interaction: discord.Interaction):
        if self._force_cleanup_player(interaction.user.id):
            await interaction.response.send_message("Your game status has been cleared.", ephemeral=True)
        else:
            await interaction.response.send_message("You don't have an active game to clear.", ephemeral=True)

    @app_commands.command(name="gamestatus", description="[DEBUG] Check your current game status.")
    async def game_status(self, interaction: discord.Interaction):
        player_id = interaction.user.id
        if player_id in self.active_games:
            game_type = self.active_games[player_id]
            await interaction.response.send_message(f"You are currently in a {game_type} game.", ephemeral=True)
        else:
            await interaction.response.send_message("You are not in any active game.", ephemeral=True)
            
    @app_commands.command(name="clearallgames", description="[ADMIN] Clear all active games.")
    @app_commands.default_permissions(administrator=True)
    async def clear_all_games(self, interaction: discord.Interaction):
        count = len(self.active_games)
        self.active_games.clear()
        await interaction.response.send_message(f"Cleared {count} active games.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ServerGames(bot))