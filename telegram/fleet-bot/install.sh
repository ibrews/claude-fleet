#!/usr/bin/env bash
# Install the fleet-bot as a launchd service (macOS) on your always-on gateway.
#
# Prereqs:
#   - Node.js 20+  (`brew install node`)
#   - An SSH key on the host machine with passwordless access to every machine
#     listed in machines.json over Tailscale.
#   - ~/claude-fleet/fleet.env with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
#   - machines.json (copy from machines.example.json and edit).

set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.claudefleet.bot"
PLIST_SRC="${BOT_DIR}/${LABEL}.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [ ! -f "${HOME}/claude-fleet/fleet.env" ]; then
    echo "ERROR: ~/claude-fleet/fleet.env missing. Create it with:"
    echo "  TELEGRAM_BOT_TOKEN=..."
    echo "  TELEGRAM_CHAT_ID=..."
    exit 1
fi
if [ ! -f "${BOT_DIR}/machines.json" ]; then
    echo "ERROR: machines.json missing. Copy machines.example.json and edit."
    exit 1
fi

cd "$BOT_DIR"
if [ ! -d node_modules ]; then
    echo "Installing node deps..."
    npm install --omit=dev
fi

NODE_BIN="$(command -v node)"
if [ -z "$NODE_BIN" ]; then
    echo "ERROR: node not on PATH"
    exit 1
fi
mkdir -p "${HOME}/Library/LaunchAgents"
sed -e "s|/usr/local/bin/node|${NODE_BIN}|" \
    -e "s|__BOT_DIR__|${BOT_DIR}|g" \
    "$PLIST_SRC" > "$PLIST_DST"

launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "Installed. Logs: /tmp/fleet-bot.log  /tmp/fleet-bot.err"
echo "Check status: launchctl list | grep ${LABEL}"
