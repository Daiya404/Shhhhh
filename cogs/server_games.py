import discord
from discord.ext import commands
from discord import app_commands, ButtonStyle
from discord.ui import View, Button
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
    "hangman_start": "Alright, I've thought of a word. Start guessing letters. You have {lives} wrong guesses before you lose.",
    "hangman_win": "You actually guessed it. The word was **{word}**. I'm impressed... for once.",
    "hangman_lose": "You lose. How disappointing. The word was **{word}**.",
    "hangman_already_guessed": "You already guessed that letter. Try to keep up."
}


# --- Word List for Hangman ---
# This list can be expanded or replaced easily.
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
class HangmanLetterButton(Button):
    def __init__(self, letter: str, **kwargs):
        super().__init__(label=letter, **kwargs)
        self.letter = letter.lower()

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_guess(interaction, self.letter)

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

        self.create_buttons()

    def create_buttons(self):
        self.clear_items()
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for i, letter in enumerate(alphabet):
            row = i // 7
            button = HangmanLetterButton(letter, style=ButtonStyle.secondary, row=row)
            if letter.lower() in self.guessed_letters or self.winner:
                button.disabled = True
            self.add_item(button)

    def get_display_word(self) -> str:
        """Returns the word with unguessed letters as underscores."""
        return " ".join([letter if letter in self.guessed_letters else "_" for letter in self.word])

    async def handle_guess(self, interaction: discord.Interaction, letter: str):
        if interaction.user != self.player:
            return await interaction.response.send_message("This isn't your game.", ephemeral=True)
        if letter in self.guessed_letters:
            return await interaction.response.send_message(PERSONALITY["hangman_already_guessed"], ephemeral=True)
        
        self.guessed_letters.add(letter)
        
        if letter not in self.word:
            self.wrong_guesses += 1

        display_word = self.get_display_word()
        embed = self.message.embeds[0]
        embed.description = f"{HANGMAN_PICS[self.wrong_guesses]}\n\n`{display_word}`"

        # Check for win/loss
        if "_" not in display_word:
            self.winner = True
            embed.color = discord.Color.green()
            embed.title = PERSONALITY["hangman_win"].format(word=self.word.upper())
            self.stop()
        elif self.wrong_guesses >= self.max_lives:
            self.winner = False
            embed.color = discord.Color.red()
            embed.title = PERSONALITY["hangman_lose"].format(word=self.word.upper())
            self.stop()

        self.create_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.winner is not None: return
        self.winner = "Timeout"
        embed = self.message.embeds[0]
        embed.title = "Game timed out."
        embed.description = f"{HANGMAN_PICS[-1]}\n\nThe word was **{self.word.upper()}**."
        self.create_buttons()
        try: await self.message.edit(embed=embed, view=self)
        except discord.NotFound: pass
        self.stop()

    async def on_stop(self):
        self.game_cog._cleanup_game([self.player])

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
        self.create_board()
    
    def create_board(self):
        self.clear_items()
        for y in range(3):
            for x in range(3):
                label, style = "\u200b", ButtonStyle.secondary
                if self.board[y][x] == "X": label, style = "❌", ButtonStyle.danger
                elif self.board[y][x] == "O": label, style = "⭕", ButtonStyle.success
                button = TicTacToeButton(x=x, y=y, label=label, style=style, row=y)
                if self.winner or self.board[y][x] != " ": button.disabled = True
                self.add_item(button)

    async def handle_move(self, interaction: discord.Interaction, x: int, y: int):
        if interaction.user != self.turn: return await interaction.response.send_message(PERSONALITY["not_your_turn"], ephemeral=True)
        if self.winner or self.board[y][x] != " ": return await interaction.response.send_message(PERSONALITY["invalid_move"], ephemeral=True)
        
        self.board[y][x] = "X" if self.turn == self.players[0] else "O"
        self.winner = self.check_for_win()
        embed = interaction.message.embeds[0]
        
        if self.winner:
            loser = self.players[1] if self.winner == self.players[0] else self.players[0]
            embed.description = PERSONALITY["win_message"].format(winner=self.winner.mention, loser=loser.mention)
            self.stop()
        elif all(cell != " " for row in self.board for cell in row):
            embed.description = PERSONALITY["draw_message"]
            self.winner = "Draw"
            self.stop()
        else:
            self.turn = self.players[1] if self.turn == self.players[0] else self.players[0]
            embed.description = f"It's **{self.turn.mention}'s** turn."
        
        self.create_board()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.winner: return
        self.winner = "Timeout"
        if self.message:
            embed = self.message.embeds[0]
            embed.description = PERSONALITY["game_timeout"]
            self.create_board()
            try: await self.message.edit(embed=embed, view=self)
            except discord.NotFound: pass
        self.stop()

    async def on_stop(self): self.game_cog._cleanup_game(self.players)

    def check_for_win(self) -> Optional[discord.Member]:
        lines = (self.board[0], self.board[1], self.board[2], [self.board[i][0] for i in range(3)], [self.board[i][1] for i in range(3)], [self.board[i][2] for i in range(3)], [self.board[i][i] for i in range(3)], [self.board[i][2-i] for i in range(3)])
        for line in lines:
            if line[0] == line[1] == line[2] != " ":
                return self.players[0] if line[0] == "X" else self.players[1]
        return None

# --- Connect4 Classes (NEW ARCHITECTURE) ---
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
        self.create_buttons()

    def create_buttons(self):
        self.clear_items()
        for i in range(7):
            button = Connect4Button(column=i, label=str(i+1), style=ButtonStyle.secondary)
            if self.winner or self.board[0][i] != " ": button.disabled = True
            self.add_item(button)

    def get_board_string(self) -> str:
        """Creates the text representation of the board."""
        emoji_map = {" ": "⚫", "X": "🔴", "O": "🟡"}
        return "\n".join("".join(emoji_map[cell] for cell in row) for row in self.board)

    async def handle_move(self, interaction: discord.Interaction, column: int):
        if interaction.user != self.turn: return await interaction.response.send_message(PERSONALITY["not_your_turn"], ephemeral=True)
        if self.winner: return

        for row in range(5, -1, -1):
            if self.board[row][column] == " ":
                self.board[row][column] = "X" if self.turn == self.players[0] else "O"
                break
        else: return await interaction.response.send_message(PERSONALITY["invalid_move"], ephemeral=True)

        self.winner = self.check_for_win()
        embed = interaction.message.embeds[0]
        
        if self.winner:
            loser = self.players[1] if self.winner == self.players[0] else self.players[0]
            embed.description = f"{self.get_board_string()}\n\n{PERSONALITY['win_message'].format(winner=self.winner.mention, loser=loser.mention)}"
            self.stop()
        elif all(cell != " " for row in self.board for cell in row):
            embed.description = f"{self.get_board_string()}\n\n{PERSONALITY['draw_message']}"
            self.winner = "Draw"
            self.stop()
        else:
            self.turn = self.players[1] if self.turn == self.players[0] else self.players[0]
            embed.description = f"{self.get_board_string()}\n\nIt's **{self.turn.mention}'s** turn."
        
        self.create_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.winner: return
        self.winner = "Timeout"
        if self.message:
            embed = self.message.embeds[0]
            embed.description = f"{self.get_board_string()}\n\n{PERSONALITY['game_timeout']}"
            self.create_buttons()
            try: await self.message.edit(embed=embed, view=self)
            except discord.NotFound: pass
        self.stop()
        
    async def on_stop(self): self.game_cog._cleanup_game(self.players)

    def check_for_win(self) -> Optional[discord.Member]:
        # Uses the same reliable logic from the previous version
        height, width, win_con = 6, 7, 4
        symbols = ["X", "O"]
        for symbol in symbols:
            player = self.players[symbols.index(symbol)]
            for y in range(height):
                for x in range(width):
                    if x <= width - win_con and all(self.board[y][x+i] == symbol for i in range(win_con)): return player
                    if y <= height - win_con and all(self.board[y+i][x] == symbol for i in range(win_con)): return player
                    if x <= width - win_con and y <= height - win_con and all(self.board[y+i][x+i] == symbol for i in range(win_con)): return player
                    if x >= win_con - 1 and y <= height - win_con and all(self.board[y+i][x-i] == symbol for i in range(win_con)): return player
        return None

# --- Main Cog Class ---
class ServerGames(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.active_games: Dict[int, str] = {}

    def _cleanup_game(self, players: List[discord.Member]):
        for player in players: self.active_games.pop(player.id, None)
        self.logger.info(f"Cleaned up game state for players: {[p.id for p in players]}")

    game_group = app_commands.Group(name="game", description="Play a game with another server member.")

    @game_group.command(name="hangman", description="Play a single-player game of Hangman.")
    async def hangman(self, interaction: discord.Interaction):
        player = interaction.user
        if self.active_games.get(player.id):
            return await interaction.response.send_message(PERSONALITY["game_already_running"], ephemeral=True)

        self.active_games[player.id] = "hangman"
        
        view = HangmanView(self, player)
        
        embed = discord.Embed(
            title="Playing Hangman!",
            description=f"{HANGMAN_PICS[0]}\n\n`{view.get_display_word()}`",
            color=discord.Color.blue()
        )
        embed.set_footer(text=PERSONALITY["hangman_start"].format(lives=view.max_lives))

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    async def _start_challenge(self, interaction: discord.Interaction, opponent: discord.Member, game_type: Literal["tictactoe", "connect4"]):
        challenger = interaction.user
        if challenger.id == opponent.id: return await interaction.response.send_message("You can't challenge yourself.", ephemeral=True)
        if opponent.bot: return await interaction.response.send_message("You can't challenge a bot.", ephemeral=True)
        if self.active_games.get(challenger.id): return await interaction.response.send_message(PERSONALITY["game_already_running"], ephemeral=True)
        if self.active_games.get(opponent.id): return await interaction.response.send_message(PERSONALITY["opponent_in_game"], ephemeral=True)

        game_name = "Tic-Tac-Toe" if game_type == "tictactoe" else "Connect 4"
        
        class ChallengeView(View):
            def __init__(self, timeout=60): super().__init__(timeout=timeout); self.accepted = None
            @discord.ui.button(label="Accept", style=ButtonStyle.success)
            async def accept(self, i: discord.Interaction, b: Button):
                if i.user != opponent: return await i.response.send_message("This isn't your challenge.", ephemeral=True)
                await i.response.defer(); self.accepted = True; self.stop()
            @discord.ui.button(label="Decline", style=ButtonStyle.danger)
            async def decline(self, i: discord.Interaction, b: Button):
                if i.user != opponent: return await i.response.send_message("This isn't your challenge.", ephemeral=True)
                await i.response.defer(); self.accepted = False; self.stop()

        view = ChallengeView()
        await interaction.response.send_message(PERSONALITY["challenge_sent"].format(challenger=challenger.mention, opponent=opponent.mention, game_name=game_name), view=view)
        
        await view.wait()
        original_message = await interaction.original_response()

        if view.accepted is True:
            self.active_games[challenger.id], self.active_games[opponent.id] = game_type, game_type
            
            if game_type == "tictactoe":
                game_view = TicTacToeView(self, challenger, opponent)
                embed = discord.Embed(title=f"Playing Tic-Tac-Toe!", description=PERSONALITY["challenge_accepted"].format(player=challenger.mention), color=discord.Color.blue())
            else: # Connect 4
                game_view = Connect4View(self, challenger, opponent)
                embed = discord.Embed(title=f"Playing Connect 4!", color=discord.Color.blue())
                embed.description = f"{game_view.get_board_string()}\n\n{PERSONALITY['challenge_accepted'].format(player=challenger.mention)}"

            await original_message.edit(content=None, embed=embed, view=game_view)
            game_view.message = original_message
        elif view.accepted is False:
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

async def setup(bot):
    await bot.add_cog(ServerGames(bot))