#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit

git reset --hard
git pull origin main
git log -1 --pretty=%B > /tmp/bot_commit_msg.txt

source venv/bin/activate
pip install -r requirements.txt

touch /tmp/bot_updated.flag
sudo systemctl restart discordbot
