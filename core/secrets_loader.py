# core/secrets_loader.py
import os
import json
from pathlib import Path
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class SecretsLoader:
    """Handles loading secrets from various sources."""
    
    @staticmethod
    def load_from_directory(path: str = "secrets") -> Dict[str, Optional[str]]:
        """Load secrets from text files in a directory."""
        secrets = {}
        secrets_path = Path(path)
        
        if not secrets_path.exists():
            logger.warning(f"Secrets directory not found: {path}")
            return secrets
        
        for file_path in secrets_path.glob("*.txt"):
            key = file_path.stem
            try:
                secrets[key] = file_path.read_text(encoding='utf-8').strip()
            except Exception as e:
                logger.error(f"Failed to read secret {key}: {e}")
                secrets[key] = None
        
        return secrets
    
    @staticmethod
    def load_from_json(path: str = "secrets/secrets.json") -> Dict[str, Optional[str]]:
        """Load secrets from a JSON file."""
        secrets_path = Path(path)
        
        if not secrets_path.exists():
            logger.warning(f"Secrets JSON not found: {path}")
            return {}
        
        try:
            with open(secrets_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load secrets JSON: {e}")
            return {}
    
    @staticmethod
    def load_from_env() -> Dict[str, Optional[str]]:
        """Load secrets from environment variables."""
        env_secrets = {}
        # Common bot secrets
        secret_keys = ['TOKEN', 'DATABASE_URL', 'DEBUG_MODE', 'DEBUG_GUILD_ID']
        
        for key in secret_keys:
            value = os.getenv(key) or os.getenv(f'BOT_{key}')
            if value:
                env_secrets[key.lower()] = value
        
        return env_secrets

def load_secrets(path: str = "secrets") -> Dict[str, Optional[str]]:
    """Main function to load secrets from multiple sources."""
    loader = SecretsLoader()
    
    # Try different sources in order of preference
    secrets = {}
    
    # 1. Environment variables (highest priority)
    secrets.update(loader.load_from_env())
    
    # 2. JSON file
    secrets.update(loader.load_from_json())
    
    # 3. Text files in directory (lowest priority)
    secrets.update(loader.load_from_directory(path))
    
    logger.info(f"Loaded {len(secrets)} secrets")
    return secrets
