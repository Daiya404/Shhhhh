import discord
from pathlib import Path

# Read the token from token.txt
token_path = Path(__file__).parent / "token.txt"
with open(token_path, "r", encoding="utf-8") as f:
    TOKEN = f.read().strip()

print(f'My Brain aint braining')

class Client(discord.Client):
    async def on_ready(self):
        print(f'Ok! Ok! I, {self.user}, am awake!')
        print('-----------')

    async def on_message(self, message):
        if message.author == self.user:
            return
        if message.content.startswith('Tika'):
            await message.channel.send(f'Oh {message.author.mention}! Did you say my name?')

intents = discord.Intents.default()
intents.message_content = True

client = Client(intents=intents)
client.run(TOKEN)
# This code initializes a Discord bot client that reads its token from a file named "token.txt".
# The bot prints a message to the console when it is ready.