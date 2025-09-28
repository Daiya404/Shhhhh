import subprocess
import sys
import os
import platform

def install_requirements():
    """Installs all required packages from requirements.txt."""
    print("Checking and installing requirements...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("All requirements are satisfied.")
    except subprocess.CalledProcessError as e:
        print(f"Error installing requirements: {e}")
        sys.exit(1)

def clear_terminal():
    """Clears the terminal screen."""
    os.system('cls' if platform.system() == 'Windows' else 'clear')

if __name__ == "__main__":
    install_requirements()
    clear_terminal()
    
    # Now that requirements are installed, we can import the bot
    from core.bot import TikaBot

    # Create and run the bot instance
    bot = TikaBot()
    bot.run()