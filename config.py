# config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# --- Core Settings ---
# Load your bot token from an environment variable for security.
# Create a file named ".env" in your project folder and add this line:
# BOT_TOKEN="YOUR_BOT_TOKEN_HERE"
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- Directory Paths ---
# This ensures our paths work correctly no matter where the bot is run from.
BASE_DIR = Path(__file__).resolve().parent
COGS_DIR = BASE_DIR / "cogs"
DATA_DIR = BASE_DIR / "data"

# Ensure the data directory exists
DATA_DIR.mkdir(exist_ok=True)