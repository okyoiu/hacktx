#!/usr/bin/env bash
# Demo only: a public https address for the Muse connector (/connector/*), then stop it (Ctrl+C) and rotate MUSE_CONNECTOR_KEY.
# The tunnel reaches the server as 127.0.0.1, so the server tells tunnelled requests apart by the forwarding headers
# the tunnel adds (X-Forwarded-For / Cf-Connecting-Ip) and answers only /connector/* to them.
set -euo pipefail
URL=http://127.0.0.1:8000

banner() {
  echo "Public tunnel to the Muse connector. Demo only: Ctrl+C when done, then change MUSE_CONNECTOR_KEY in .env."
  echo "Give Muse <public url>/connector/openapi.json and the key. Nothing else is reachable through it."
}

if command -v cloudflared >/dev/null; then
  banner
  # print the address on its own line when cloudflared logs it
  cloudflared tunnel --url "$URL" 2>&1 | while IFS= read -r line; do
    echo "$line"
    url=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' <<<"$line" || true)
    [ -n "$url" ] && echo ">>> Public URL: $url"
  done
elif command -v ngrok >/dev/null; then
  banner
  echo "ngrok shows the public address in its window."
  ngrok http "$URL"
else
  echo "No tunnel tool found. Install one, then run this again:  brew install cloudflared   (or ngrok: https://ngrok.com/download)" >&2
  exit 1
fi
