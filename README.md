# Tika Bot 🤖

A sassy, efficient, and powerful multi-purpose Discord bot.

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![discord.py](https://img.shields.io/badge/discord.py-2.5.2-7289DA.svg)](https://github.com/Rapptz/discord.py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## About Tika

Tika is not just another Discord bot. She's a high-performance assistant designed to manage a server with a unique personality. She's helpful and respects everyone, but has little patience for mistakes or time-wasting. She combines powerful moderation and utility features with fun, customizable commands to create a complete server management solution.

## ✨ Features

Tika is built with a fully modular, cog-based architecture. All commands are slash commands unless specified otherwise.

### 🛡️ Moderation

*   **Detention System:** A unique, interactive timeout system. An admin can place a user in "detention," stripping their roles and confining them to a single channel until they've typed a specific sentence a set number of times. All roles are automatically restored upon completion.
*   **Word Blocker:** A highly efficient, regex-powered system to block words. Words can be blocked **globally** or on a **per-user** basis. It intelligently matches whole words and handles message edits.
*   **Chat Clear:** Includes a standard `/clear` command and a unique two-step prefix command (`!tika eat`/`!tika end`) to delete a specific range of messages.

### 🛠️ Utility

*   **Link Fixer:** Automatically detects broken `twitter.com` and `x.com` links and reposts them using `vxtwitter.com` to ensure embeds work correctly. Features both a global toggle for admins and a personal toggle for users.
*   **Auto-Reply (Server Lore):** Set up custom trigger words that Tika will automatically reply to. A core part of the bot, managed with the `/nga` command group.

### 🎉 Fun & Games

*   **Coinflip, Dice Roll & RPS:** Classic fun commands with personality-driven responses.
*   **Dynamic Embeds:** Admins can add a custom pool of GIFs/images for each fun command, making the bot's responses unique to your server.
*   **GIF Toggle:** Users can disable the GIF on the `/roll` command for a compact, text-based response, perfect for spamming rolls.

### 🎨 Customization

*   **Custom Roles:** Allows users to create and manage their own personal, custom-colored role with `/role set`.
*   **Dynamic Positioning:** Admins can set "marker" roles, and Tika will intelligently place all user roles directly above them in the hierarchy.

### ⚙️ Administration

*   **Bot Admins:** A flexible permission system. Server Administrators can grant trusted, non-admin users permission to use Tika's admin commands.
