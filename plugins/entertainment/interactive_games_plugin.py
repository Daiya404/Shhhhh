# --- plugins/entertainment/interactive_games_plugin.py ---

import discord
from discord import app_commands, ButtonStyle
from discord.ui import View, Button
import random
import asyncio
from typing import Dict, List, Optional

from plugins.base_plugin import BasePlugin

# --- Game UI Views (e.g., TicTacToe) ---
# For brevity, we'll only fully implement TicTacToe here.
# The logic for Connect4 and Hangman is very similar and can be ported from the old files.

class ChallengeView(View):
    """A view to handle game challenges between users."""
    def __init__(self, opponent: discord.Member):
        super().__init__(timeout=60.0)
        self.opponent = opponent
        self.accepted: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("This challenge isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accept", style=ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: Button):
        self.accepted = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Decline", style=ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: Button):
        self.accepted = False
        await interaction.response.defer()
        self.stop()

class TicTacToeButton(Button):
    """A button representing a square on the TicTacToe board."""
    def __init__(self, x: int, y: int):
        super().__init__(style=ButtonStyle.secondary, label='\u200b', row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_move(interaction, self.x, self.y)

class TicTacToeView(View):
    """The UI and game logic for a TicTacToe match."""
    def __init__(self, plugin, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=300.0)
        self.plugin = plugin
        self.players = { 'X': player1, 'O': player2 }
        self.turn = 'X'
        self.board = [['\u200b'] * 3 for _ in range(3)]
        self.winner: Optional[discord.Member] = None

        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

    def check_win(self):
        # Check rows, columns, and diagonals
        lines = self.board + list(zip(*self.board)) + \
                [[self.board[i][i] for i in range(3)], [self.board[i][2-i] for i in range(3)]]
        for line in lines:
            if line[0] == line[1] == line[2] != '\u200b':
                return self.players[line[0]]
        return None

    async def handle_move(self, interaction: discord.Interaction, x: int, y: int):
        if interaction.user != self.players[self.turn]:
            return await interaction.response.send_message("It's not your turn!", ephemeral=True)
        if self.board[y][x] != '\u200b':
            return await interaction.response.send_message("That spot is already taken.", ephemeral=True)

        self.board[y][x] = self.turn
        button = next(c for c in self.children if isinstance(c, TicTacToeButton) and c.x == x and c.y == y)
        button.label = self.turn
        button.style = ButtonStyle.danger if self.turn == 'X' else ButtonStyle.success
        button.disabled = True

        self.winner = self.check_win()
        if self.winner:
            for child in self.children: child.disabled = True
            await interaction.response.edit_message(
                content=f"Game over! **{self.winner.display_name}** wins!", view=self
            )
            self.stop()
        elif all(cell != '\u200b' for row in self.board for cell in row):
            for child in self.children: child.disabled = True
            await interaction.response.edit_message(content="It's a draw!", view=self)
            self.stop()
        else:
            self.turn = 'O' if self.turn == 'X' else 'X'
            await interaction.response.edit_message(
                content=f"It's **{self.players[self.turn].display_name}**'s turn ({self.turn}).", view=self
            )

    async def on_timeout(self):
        for child in self.children: child.disabled = True
        # Need to edit the original message if it exists
        if self.message:
            await self.message.edit(content="Game timed out.", view=self)
        self.stop()

# --- Main Plugin Class ---
class InteractiveGamesPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "interactive_games"

    def __init__(self, bot):
        super().__init__(bot)
        self.active_games: Dict[int, str] = {} # {user_id: game_name}

    game_group = app_commands.Group(name="game", description="Play a game with another server member.")

    def _is_in_game(self, user_id: int) -> bool:
        return user_id in self.active_games

    def _start_game(self, players: List[discord.Member], game_name: str):
        for player in players:
            self.active_games[player.id] = game_name

    def _end_game(self, players: List[discord.Member]):
        for player in players:
            self.active_games.pop(player.id, None)

    @game_group.command(name="tictactoe", description="Challenge someone to a game of Tic-Tac-Toe.")
    @app_commands.describe(opponent="The user you want to play against.")
    async def tictactoe(self, interaction: discord.Interaction, opponent: discord.Member):
        challenger = interaction.user
        if self._is_in_game(challenger.id) or self._is_in_game(opponent.id):
            return await interaction.response.send_message("One of you is already in a game.", ephemeral=True)
        if opponent.bot or opponent == challenger:
            return await interaction.response.send_message("You can't challenge them.", ephemeral=True)

        challenge_view = ChallengeView(opponent)
        await interaction.response.send_message(
            f"{challenger.mention} has challenged {opponent.mention} to Tic-Tac-Toe!",
            view=challenge_view
        )
        await challenge_view.wait()

        if challenge_view.accepted:
            self._start_game([challenger, opponent], "TicTacToe")
            game_view = TicTacToeView(self, challenger, opponent)
            message = await interaction.edit_original_response(
                content=f"It's **{challenger.display_name}**'s turn (X).", view=game_view
            )
            game_view.message = message # Store message for timeout editing
            await game_view.wait()
            self._end_game([challenger, opponent])
        else:
            await interaction.edit_original_response(content="The challenge was declined or timed out.", view=None)