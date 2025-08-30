# Tika Bot 🤖

A sassy, efficient, and powerful multi-purpose Discord bot designed for complete server management and community engagement.

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![discord.py](https://img.shields.io/badge/discord.py-2.5.2-7289DA.svg)](https://github.com/Rapptz/discord.py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## About Tika

Tika is not just another Discord bot. She's a high-performance assistant with a unique personality, built to handle everything a modern server needs. She is helpful and respects competent users but has little patience for mistakes or time-wasting. She combines powerful moderation and utility with deep customization, engaging games, and an AI-powered brain to create a truly all-in-one solution.

## ✨ Complete Feature List

Tika is built with a fully modular, cog-based architecture. All commands are slash commands unless specified otherwise.

### 🧠 AI Integration

- **Context-Aware Chat:** Mention Tika (`@Tika-Alpha`) to start a conversation. She reads the recent chat history to understand the context, providing intelligent and in-character responses powered by the Gemini API.
- **Conversation Summary:** Use `/summarize` to get a concise, AI-generated summary of the last `X` messages in a channel, perfect for catching up.
- **Self-Learning:** Admins can provide Tika with URLs to learn about her own persona, which she integrates into her knowledge base.

### 🛡️ Moderation

- **Detention System:** A unique, interactive timeout. Admins can place a user in a designated `#detention` channel until they've typed a specific sentence a set number of times. Roles are automatically stripped and restored. The system is abuse-proof, preventing inescapable sentences.
- **Word Blocker:** A highly efficient, regex-powered system to block words **globally** or on a **per-user** basis. It intelligently matches whole words, handles message edits, and works for all users (including admins).
- **Chat Clear:** Includes a standard `/clear` command and a unique two-step prefix command (`!tika eat` / `!tika end`) to delete a specific range of messages.
- **Copy Chapel (Starboard):** A stylish and robust starboard system. Users can react with a custom server emote to "quote" a message to a designated `#chapel` channel. The bot handles replies, live-updates the reaction count, and locks the original message content.

### 🛠️ Utility & Automation

- **Link Fixer:** Automatically detects broken `twitter.com` and `x.com` links and reposts them using `vxtwitter.com` to ensure embeds work correctly. Features both a global toggle for admins and a personal toggle for users.
- **Auto-Reply:** Set up custom trigger words (`/nga`) that Tika will automatically reply to with text or images. A core feature for server lore and memes.
- **Reminders & Timers:** A full-featured system allowing users to set personal reminders and timers with natural language (`1d 30m`). Supports repeating reminders, admin management, and user-configurable delivery (DM or channel).
- **Twitter Feed:** Admins can set up the bot to monitor a Twitter account (via an RSS bridge) and automatically post new tweets to a designated channel.

### 💖 Social & Leveling System

- **XP & Levels:** Users gain XP for chatting. The system is fully customizable by admins, including XP rates and cooldowns.
- **Pillow-Powered Rank Cards:** A beautiful, custom-generated `/rank` card that displays a user's avatar, level, rank, and a progress bar.
- **Customizable Rank Cards:** Users can set their own custom background image and accent color for their personal rank card.
- **Automatic Role Rewards:** Admins can configure specific roles to be automatically granted (and previous roles removed) at level milestones (10, 20, 30, etc.).

### 🎉 Fun & Games

- **Tic-Tac-Toe, Connect 4, Hangman:** A suite of classic, interactive games with robust UI and state management.
- **Resign Command:** Players can gracefully exit any active game using `/game resign`.
- **Coinflip, Dice Roll & RPS:** Classic fun commands with sass and personality.
- **Dynamic Embeds:** Admins can add a custom pool of GIFs/images for each fun command.
- **GIF Toggle:** Users can disable the GIF on the `/roll` command for a compact, text-based response.

---

## 🚀 Getting Started

Follow these steps to get your own instance of Tika running.

### Prerequisites

- Python 3.10 or higher
- A **Discord Bot Token**
- A **Gemini API Key** for the AI features.

### Installation

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/your-username/TikaBot.git
    cd TikaBot
    ```

2.  **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

3.  **Create the `.env` file:**

    - Create a new file in the main directory called `.env`.
    - Add your Gemini API key to this file:

      ```GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE"

      ```

4.  **Create the `token.txt` file:**

    - Create a new file in the main directory called `token.txt`.
    - Paste **only** your Discord bot token into this file and save it.

5.  **Create `assets` folder:**

    - Create a folder named `assets` in the main directory.
    - Inside `assets`, create a folder named `fonts`.
    - Place a `.ttf` or `.otf` font file inside `assets/fonts` and ensure it is named `unisans.otf` (or update the font name in the code).

6.  **Run the bot:**
    ```bash
    python bot.py
    ```

### Initial Server Setup

After inviting the bot, an admin must configure some features for them to work:

- **Detention:** Create a role named `BEHAVE` and use `/detention set-channel` to designate a channel.
- **Copy Chapel:** Use `/chapel-admin` to set the channel, emote, and threshold.
- **Leveling Roles:** Use `/level-admin set-level-role` to configure role rewards.

---

## ⚖️ Required Permissions

For full functionality without granting `Administrator`, Tika's role needs the following permissions:

- **Manage Roles** (Detention, Custom Roles, Leveling Roles)
- **Manage Messages** (Clear, Word Blocker, Chapel)
- **Manage Webhooks** (Link Fixer)
- **Read Message History** (Clear, Summarize)
- **Send Messages** & **Embed Links**
- **Add Reactions** (Chapel, Word Game)

**Crucially, for Tika to manage roles, her role must be positioned higher than the roles she needs to assign/remove in your server's role hierarchy.**

---

## 📜 License

This project is licensed under the MIT License.
