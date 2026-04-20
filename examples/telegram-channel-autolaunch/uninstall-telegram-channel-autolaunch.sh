#!/bin/bash
# Undo Telegram channel auto-launch. Kills tmux session + launchd agent.
#
# See examples/telegram-channel-autolaunch/README.md for setup.

set -euo pipefail

# ------------------------------------------------------------------
# Parameters — must match the label you used in the plist and
# the tmux session name in start-telegram-channel-session.sh.
# ------------------------------------------------------------------
AGENT_LABEL="REPLACE_ME_LABEL"
AGENT_PLIST="$HOME/Library/LaunchAgents/${AGENT_LABEL}.plist"
TMUX_BIN="/opt/homebrew/bin/tmux"
SESSION="telegram-channel"
# ------------------------------------------------------------------

if [ -f "$AGENT_PLIST" ]; then
    launchctl unload "$AGENT_PLIST" 2>/dev/null || true
    rm -f "$AGENT_PLIST"
    echo "Removed launchd agent: $AGENT_PLIST"
fi

if "$TMUX_BIN" has-session -t "$SESSION" 2>/dev/null; then
    "$TMUX_BIN" kill-session -t "$SESSION"
    echo "Killed tmux session: $SESSION"
fi

pkill -f '^claude --channels plugin:telegram' 2>/dev/null || true
echo "Done."
