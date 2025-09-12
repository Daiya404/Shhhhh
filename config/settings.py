# config/settings.py
from pathlib import Path

# This helper function reads a key from a file in the root directory.
def _load_key_from_file(filename: str) -> str:
    base_dir = Path(__file__).resolve().parent.parent
    file_path = base_dir / filename
    if not file_path.exists():
        return ""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # .strip() is crucial to remove accidental newlines or spaces
            return f.read().strip()
    except Exception:
        return ""

class Settings:
    # Load keys from .txt files
    TOKEN: str = _load_key_from_file("token.txt")
    GEMINI_API_KEY: str = _load_key_from_file("gemini_api.txt")
    
    # The rest of the settings remain the same
    COMMAND_PREFIX: tuple = ("!tika ", "!Tika ")
    
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    LOGS_DIR: Path = BASE_DIR / "logs"
    COGS_DIR: Path = BASE_DIR / "cogs"

settings = Settings()