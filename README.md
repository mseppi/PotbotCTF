# PotBot

A fresh Discord bot built on the PotBot auto-update pipeline.

## Setup

1. Create a `.env` file:

   ```
   DISCORD_TOKEN=your_bot_token
   GITHUB_WEBHOOK_SECRET=your_webhook_secret
   ```

2. Create a virtual environment and install dependencies:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Create a systemd service (`/etc/systemd/system/discordbot.service`):

   ```ini
   [Unit]
   Description=PotBot Discord Bot
   After=network.target

   [Service]
   Type=simple
   User=<your_user>
   WorkingDirectory=/home/<your_user>/PotBot
   ExecStart=/home/<your_user>/PotBot/venv/bin/python bot.py
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

4. Create a systemd service for the webhook listener (`/etc/systemd/system/potbot-webhook.service`):

   ```ini
   [Unit]
   Description=PotBot GitHub Webhook Listener
   After=network.target

   [Service]
   Type=simple
   User=<your_user>
   WorkingDirectory=/home/<your_user>/PotBot
   ExecStart=/home/<your_user>/PotBot/venv/bin/python webhook_listener.py
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

5. Enable and start:
   ```bash
   sudo systemctl enable discordbot
   sudo systemctl start discordbot
   sudo systemctl enable potbot-webhook
   sudo systemctl start potbot-webhook
   ```

## Auto-Update Pipeline

Push to `main` → GitHub webhook hits `/github-webhook` on port 5001 → `update_bot.sh` pulls, installs deps, restarts → bot sends commit message to Discord channel on startup.

## Commands

- `!ping` — Check bot latency

test commit
