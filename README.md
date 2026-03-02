# PotBot

Discord bot with auto-update via GitHub webhooks.

## Setup

1. Create `.env` with `DISCORD_TOKEN` and `GITHUB_WEBHOOK_SECRET`.
2. Create venv and install deps: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
3. Enable systemd services: `discordbot` (runs `bot.py`) and `potbot-webhook` (runs `webhook_listener.py` on port 5001).
4. Expose port 5001 with ngrok: `ngrok http 5001`
5. Add a GitHub webhook pointing to `https://<ngrok-url>/github-webhook` (Content type: `application/json`, secret from `.env`).

## Auto-Update

Push to `main` → GitHub webhook → `update_bot.sh` pulls & restarts → bot posts commit message to Discord.

## Commands

- `!ping` — Check bot latency
