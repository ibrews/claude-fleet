#!/bin/bash
# Start (or restart) the dedicated Telegram channel session inside a tmux session.
# Runs via launchd at login; also manually re-runnable.
#
# The session is interactive (claude is a TUI) so we wrap it in tmux to give it a PTY.
# Attach with: tmux attach -t telegram-channel
# Undo:        ~/.claude/scripts/uninstall-telegram-channel-autolaunch.sh
#
# See examples/telegram-channel-autolaunch/README.md for setup and placeholders.

set -euo pipefail

TMUX_BIN="/opt/homebrew/bin/tmux"
CLAUDE_BIN="/opt/homebrew/bin/claude"
[ -x "$CLAUDE_BIN" ] || CLAUDE_BIN="$(command -v claude || echo claude)"

# ------------------------------------------------------------------
# Parameters — edit these (or run the sed substitution from README).
# ------------------------------------------------------------------
SESSION="telegram-channel"
KB_DIR="REPLACE_ME_KB_DIR"
CHANNEL_FLAG="plugin:telegram@claude-plugins-official"
LOG="$HOME/.claude/logs/telegram-channel.log"
# ------------------------------------------------------------------

mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# Kill stale tmux session if present
if "$TMUX_BIN" has-session -t "$SESSION" 2>/dev/null; then
    "$TMUX_BIN" kill-session -t "$SESSION"
    log "killed stale tmux session"
fi

# Kill orphan `claude --channels` processes that aren't part of a Desktop session.
# (Desktop wrappers invoke claude.real; only bare terminal `claude --channels` matches.)
pkill -f '^claude --channels plugin:telegram' 2>/dev/null || true
sleep 1

# Spawn fresh session
"$TMUX_BIN" new-session -d -s "$SESSION" -c "$KB_DIR" \
    "exec '$CLAUDE_BIN' --channels '$CHANNEL_FLAG'"

log "started tmux session '$SESSION' in $KB_DIR"
