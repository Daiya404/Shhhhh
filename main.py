# main.py
import subprocess
import sys
import os

def check_and_install_requirements():
    """Checks if all required packages in requirements.txt are installed and installs them if not."""
    print("Checking required packages...")
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        print("All packages are up to date.")
    except subprocess.CalledProcessError as e:
        print(f"Error during package installation: {e}")
        sys.exit(1)

def main():
    """Main function to load secrets and run the bot."""
    # Check dependencies first
    check_and_install_requirements()

    # Now that we know dependencies are installed, we can import our modules
    from core.bot import TikaBot
    from core.secrets_loader import load_secrets

    # Load secrets from the 'secrets' folder
    secrets = load_secrets()
    token = secrets.get("token")

    if not token:
        print("Error: 'token.txt' not found or is empty in the 'secrets' directory.")
        sys.exit(1)
        
    # Initialize and run the bot
    # You can also pass all secrets to the bot if other cogs need them
    bot = TikaBot()
    bot.secrets = secrets  # Attach secrets to the bot instance for easy access
    bot.run(token)

if __name__ == "__main__":
    main()