# core/secrets_loader.py
import os
from typing import Dict, Optional
import logging

def load_secrets(path: str = "secrets") -> Dict[str, Optional[str]]:
    """
    Loads all secrets from text files in a specified directory.

    The function reads each .txt file in the directory, using the filename
    (without extension) as the key for the secret.

    Args:
        path (str): The relative path to the secrets directory.

    Returns:
        A dictionary mapping secret names to their values.
    """
    secrets: Dict[str, Optional[str]] = {}
    
    if not os.path.isdir(path):
        logging.error(f"Secrets directory not found at: '{path}'")
        return secrets

    for filename in os.listdir(path):
        if filename.endswith(".txt"):
            key = filename[:-4]  # Remove .txt extension
            filepath = os.path.join(path, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    # Read the content and strip any leading/trailing whitespace
                    secrets[key] = f.read().strip()
            except Exception as e:
                logging.error(f"Failed to read secret from {filename}: {e}")
                secrets[key] = None
    
    return secrets