#!/bin/bash
# Print the active ngrok public URL for the webhook endpoint
URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; t=json.load(sys.stdin)['tunnels']; print(next(t['public_url'] for t in t if t['proto']=='https'))" 2>/dev/null)
if [ -z "$URL" ]; then
    echo "ngrok is not running or tunnel not ready yet"
    exit 1
fi
echo "Webhook URL: $URL/github-webhook"
