#!/bin/bash
# Claude Code Stop Hook: Auto-commit KB + generate per-machine daily log
#
# When a Claude session ends, this hook:
# 1. Commits any modified files in the shared knowledge base
# 2. Auto-generates a per-machine daily log entry if Claude didn't write one
# 3. Pushes to remote
#
# Daily log convention:
#   daily/YYYY-MM-DD-<machine>.md  — per-machine session details (auto or manual)
#   daily/YYYY-MM-DD.md            — fleet rollup (announcements, cross-machine events)
#
# Install: Add to ~/.claude/settings.json under hooks.Stop

set -euo pipefail

KB_DIR="${KB_DIR:-$HOME/knowledge}"
MACHINE_NAME="${KB_MACHINE_NAME:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
TODAY=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%H:%M)
MACHINE_LOG="$KB_DIR/daily/$TODAY-$MACHINE_NAME.md"

if [ ! -d "$KB_DIR/.git" ]; then
    exit 0
fi

cd "$KB_DIR"

if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    exit 0
fi

git add -A

# Auto-generate per-machine log if Claude didn't write one this session
MACHINE_LOG_TOUCHED=false
if git diff --cached --name-only | grep -q "^daily/$TODAY-$MACHINE_NAME.md"; then
    MACHINE_LOG_TOUCHED=true
fi

if [ "$MACHINE_LOG_TOUCHED" = false ] && [ -d "$KB_DIR/daily" ]; then
    CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null || true)
    FILE_COUNT=$(echo "$CHANGED_FILES" | grep -c '[^[:space:]]' || echo "0")

    if [ ! -f "$MACHINE_LOG" ]; then
        cat > "$MACHINE_LOG" << HEADER
---
title: "Daily Log — $TODAY — $MACHINE_NAME"
updated: $TODAY
tags: [daily, $MACHINE_NAME]
---

# $TODAY — $MACHINE_NAME

HEADER
    fi

    {
        echo ""
        echo "### Session @ $TIMESTAMP (auto-logged)"
        if [ "$FILE_COUNT" -gt 0 ]; then
            echo "Modified $FILE_COUNT files:"
            echo "$CHANGED_FILES" | head -15 | while read -r f; do
                [ -n "$f" ] && echo "- \`$f\`"
            done
            [ "$FILE_COUNT" -gt 15 ] && echo "- ...and $((FILE_COUNT - 15)) more"
        else
            echo "Session ended with no KB file changes."
        fi
    } >> "$MACHINE_LOG"

    git add "$MACHINE_LOG"
fi

# Commit
SAFE_MACHINE=$(echo "$MACHINE_NAME" | tr -d '"$`\\!&|;/' | cut -c1-40)
git commit -m "chore(kb): auto-sync from $SAFE_MACHINE session-end $TODAY-$TIMESTAMP" --quiet 2>/dev/null || true

# Pull and push — log failures for debugging
LOG_FILE="/tmp/fleet-session-end.log"
git pull --rebase origin master --quiet 2>>"$LOG_FILE" || {
    echo "[$(date +%Y-%m-%dT%H:%M:%S)] git pull --rebase failed (exit $?)" >> "$LOG_FILE"
}
if ! git push origin master --quiet 2>>"$LOG_FILE"; then
    echo "[$(date +%Y-%m-%dT%H:%M:%S)] git push failed (exit $?) — committed locally but not pushed" >> "$LOG_FILE"
fi

exit 0
