# PC Monitoring Bot - Deployment Guide

## HOW TO RUN THE BOT
================================

1. Install Python 3.9 or newer: https://python.org
   (Make sure to check the box "Add Python to PATH" during installation).
2. Extract this project into a dedicated folder (e.g., `C:\my_bot` or your local workspace).
3. Open your terminal or Command Prompt in that project folder and install the required dependencies:
       pip install -r requirements.txt
4. Configure your environment variables:
   * Open the `.env` file using any text editor (like Notepad).
   * Fill in your `BOT_TOKEN` (received from @BotFather) and your personal Telegram `ADMIN_ID`.
   ⚠️ WARNING: Never share this file or upload it to public networks (e.g., GitHub, open chats). Your token functions as a password to control your host system.
5. Launch the bot application:
       python bot.py
   The bot will remain active as long as this terminal window stays open. To stop the process, press `Ctrl+C`.
6. Open your bot interface in Telegram and send the `/start` command to initialize it.

Security Note: If your token is ever compromised or exposed publicly, immediately revoke it via @BotFather using the `/revoke` command, then generate and update a new one inside your `.env` file.
