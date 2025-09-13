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
    # Define the base directory as the root of the project
    # __file__ is config/settings.py -> .parent is config/ -> .parent is the project root
    base_dir = Path(__file__).resolve().parent.parent
    
    # Correctly build the path to the secrets folder
    secrets_dir = base_dir / "secrets"
    file_path = secrets_dir / filename
    
    # --- DEBUGGING LINE ---
    # You can uncomment the line below to see the exact path it's checking
    # print(f"Attempting to read key from: {file_path}")
    
    if not file_path.exists():
        # Make the error message more helpful
        logger.warning(f"SECRET FILE NOT FOUND: Could not find '{file_path}'. Make sure it exists.")
        # Create the secrets folder if it's missing, to help the user.
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
    # Load keys from their new location
    TOKEN: str = _load_key_from_file("token.txt")
    GEMINI_API_KEY: str = _load_key_from_file("gemini_api.txt")
    
    # The rest of the settings remain the same
    COMMAND_PREFIX: tuple = ("!tika ", "!Tika ")
    
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    LOGS_DIR: Path = BASE_DIR / "logs"
    COGS_DIR: Path = BASE_DIR / "cogs"
    ASSETS_DIR: Path = BASE_DIR / "assets"

settings = Settings()