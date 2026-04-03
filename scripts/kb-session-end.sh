#!/bin/bash
# Claude Code Stop Hook: Auto-commit and push KB changes
#
# When a Claude session ends, this hook commits any modified files
# in the shared knowledge base and pushes them. This ensures no
# work is lost between sessions.
#
# Install: Add to ~/.claude/settings.json under hooks.Stop

set -euo pipefail

# Use ~/knowledge — never access ~/.claude/ directly (causes permission prompts)
KB_DIR="${KB_DIR:-$HOME/knowledge}"
MACHINE_NAME="${KB_MACHINE_NAME:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
TODAY=$(date +%Y-%m-%d)

# Bail if KB dir doesn't exist or isn't a git repo
if [ ! -d "$KB_DIR/.git" ]; then
    exit 0
fi

cd "$KB_DIR"

# Check for any changes (staged, unstaged, or untracked)
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    exit 0
fi

# Stage all changes
git add -A

# Commit
TIMESTAMP=$(date +%H%M)
git commit -m "chore(kb): auto-sync from $MACHINE_NAME session-end $TODAY-$TIMESTAMP" --quiet 2>/dev/null || true

# Pull (rebase to avoid merge commits) and push
# Log failures so users can debug (hooks run silently)
LOG_FILE="/tmp/fleet-session-end.log"
git pull --rebase origin master --quiet 2>>"$LOG_FILE" || {
    echo "[$(date +%Y-%m-%dT%H:%M:%S)] git pull --rebase failed (exit $?)" >> "$LOG_FILE"
}
if ! git push origin master --quiet 2>>"$LOG_FILE"; then
    echo "[$(date +%Y-%m-%dT%H:%M:%S)] git push failed (exit $?) — KB changes committed locally but not pushed" >> "$LOG_FILE"
fi

exit 0
