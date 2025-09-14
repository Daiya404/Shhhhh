# Tika Bot

Tika is a sophisticated, multi-purpose Discord bot designed for robust server management, engaging community interaction, and intelligent, in-character AI conversation. Built on a modern, scalable architecture, Tika combines powerful administrative tools with a unique, composed personality, making her feel less like a tool and more like a true participant in the server.

## ✨ Key Features

Tika's functionality is organized into modular cogs, ensuring stability and performance.

### 🧠 AI & Interaction

- **Conversational AI (`/chat`, Replies):** Engage in natural, multi-turn conversations with Tika. Her personality adapts based on her relationship with a user, from hesitant with newcomers to open and witty with friends.
- **Web Search Integration (@mention):** Ask Tika factual questions by mentioning her. She will search the web to find the answer and deliver it with her signature personality.
- **Conversation Summarization (@mention):** Mention Tika with the word "summarize" to get a concise, in-character summary of the last 50 messages in the channel.
- **Proactive Engagement (Opt-in):** In a configured channel, Tika can intelligently analyze the ongoing conversation and occasionally interject with her own relevant, in-character comments.

### 🛡️ Moderation Suite

- **Word Blocker (`/blockword`):** A high-performance system to block unwanted words, with support for both global and per-user blocklists.
- **Advanced Link Fixer:** Automatically fixes embeds for popular social media platforms (Twitter/X, Instagram, TikTok, Reddit, Pixiv). Each user can toggle this feature for themselves.
- **Auto-Reply (`/autoreply`):** Configure custom text or media replies that trigger on specific keywords.
- **Detention System (`/detention`):** A robust system to temporarily restrict a user's messages to a specific channel, where they must complete a task to be released.

### 🛠️ Administration & Utility

- **Powerful Clear Commands (`/clear`, `/clearsearch`, `!tika eat`):** A full suite of tools for message pruning, including bulk deletion, user-specific deletion, and targeted searching.
- **Bot Admin Delegation (`/botadmin`):** Server owners can grant trusted, non-admin members permission to use Tika's administrative commands.
- **Granular Feature Manager (`/feature-manager`):** Enable or disable any of Tika's core features on a per-server basis for complete control.
- **Automated Backups (`/backup`):** Automatically backs up all server data (settings, scores, etc.) to a private Google Drive folder, ensuring data is never lost.
- **Performance Monitoring (`/performance`):** Check the bot's real-time RAM usage, latency, and uptime.
- **Personalized Reminders (`/remind`):** A streamlined system for users to set, list, and delete personal reminders.
- **Custom Roles (`/personal-role`):** Allow users to create and customize their own personal role with a unique name and color.
- **Copy Chapel (`/chapel-admin`):** Designate a channel where messages that receive a certain number of a specific reaction are automatically copied.

### 🎉 Fun & Games

- **Classic Commands (`/coinflip`, `/roll`, `/rps`):** Standard fun commands with Tika's unique personality.
- **Server Games (`/play`):** Challenge other server members to persistent games of Tic-Tac-Toe and Connect 4.
- **Word Chain Game:** A continuous, channel-wide word game where users build on the last letter of the previous word to score points.

## 🚀 Setup & Installation

1.  **Clone the Repository:**

    ```bash
    git clone https://github.com/Daiya404/Shhhhh/tree/main
    ```

2.  **Create a Virtual Environment (Recommended):**

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Secrets:**
    In the root of the project, create a `secrets` folder. Inside this folder, create the following files:

    - `token.txt`: Your Discord Bot Token.
    - `gemini_api.txt`: Your Google Gemini API Key for the AI.
    - `owner_email.txt`: Your personal `@gmail.com` address, for the bot to share its backup folder with.
    - `gdrive_credentials.json`: The JSON key file for your Google Cloud Service Account.

5.  **Configure Assets:**
    In the root of the project, create an `assets` folder. Inside it, you must have:

    - `dictionary.txt`: A text file containing a list of English words, one per line, for the Word Game.

6.  **Run the Bot:**
    ```bash
    python main.py
    ```

## ⚙️ Usage & Configuration

- Most user-facing commands are available via slash commands (`/`).
- Administrative commands (like `/botadmin`, `/feature-manager`, etc.) are only visible to server administrators by default.
- Use `/feature-manager` to see a list of all toggleable features and customize Tika's behavior for your server.
