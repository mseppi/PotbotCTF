from flask import Flask, request
import subprocess
import hmac
import hashlib
import os
import pathlib

app = Flask(__name__)

# Resolve update script path relative to this file
BASE_DIR = pathlib.Path(__file__).resolve().parent
UPDATE_SCRIPT = str(BASE_DIR / "update_bot.sh")

# Secret for GitHub webhook (set in webhook settings)
WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

@app.route("/github-webhook", methods=["GET"])
def github_webhook_test():
    return "GitHub webhook listener is running", 200

@app.route("/github-webhook", methods=["POST"])
def github_webhook():
    # Validate GitHub webhook signature
    signature = request.headers.get("X-Hub-Signature-256")
    body = request.data
    hash = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, hash):
        return "Invalid signature", 403

    # Only update on pushes to main branch
    payload = request.get_json()
    if payload.get("ref") != "refs/heads/main":
        return "Ignored: not main branch", 200

    # Pull latest code and restart bot
    subprocess.call([UPDATE_SCRIPT])
    return "Bot updated", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
