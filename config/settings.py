# config/settings.py
from pathlib import Path
import logging

# Get a logger for this module
logger = logging.getLogger(__name__)


def _load_key_from_file(filename: str) -> str:
    """
    Loads a key from a file within the 'secrets' directory, which is
    located in the project's root folder.
    """
    base_dir = Path(__file__).resolve().parent.parent

    # Correctly build the path to the secrets folder
    secrets_dir = base_dir / "secrets"
    file_path = secrets_dir / filename

    if not file_path.exists():
        logger.warning(f"SECRET FILE NOT FOUND: Could not find '{file_path}'. Make sure it exists.")
        # Create the secrets folder if it doesn't exist
        if not secrets_dir.exists():
            logger.info(f"Creating missing directory: {secrets_dir}")
            secrets_dir.mkdir()
        return ""

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception as e:
        logger.error(f"Failed to read key from {file_path}", exc_info=e)
        return ""


class Settings:
    # --- Core Bot Secrets ---
    # We load the bot token from a file to keep it out of our code.
    TOKEN: str = _load_key_from_file("token.txt")

    # --- Directory Paths ---
    # These paths allow the bot to know where its files are.
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    COGS_DIR: Path = BASE_DIR / "cogs"
    DATA_DIR: Path = BASE_DIR / "data"
    LOGS_DIR: Path = BASE_DIR / "logs"


# Create a single, accessible instance of the settings
settings = Settings()