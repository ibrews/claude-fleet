#!/usr/bin/env bash
# Send a notification to another fleet machine.
# Bash equivalent of send-notification.js — writes a JSON file to
# ~/knowledge/notifications/<target>/ and git pushes.
#
# Usage: send-notification.sh <target-machine> <subject> <message> [priority]
#
# Example:
#   send-notification.sh alpha "Build complete" "Built v1.2.0, uploaded to TestFlight" normal
#
# Priority: "normal" (default) or "urgent"

set -euo pipefail

TARGET="${1:-}"
SUBJECT="${2:-}"
MESSAGE="${3:-}"
PRIORITY="${4:-normal}"

if [ -z "$TARGET" ] || [ -z "$SUBJECT" ]; then
    echo "Usage: send-notification.sh <target-machine> <subject> <message> [priority]" >&2
    echo "  priority: \"normal\" (default) or \"urgent\"" >&2
    exit 1
fi

# Detect sender machine name
FROM="${FLEET_MACHINE_NAME:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"

# KB path
KB_DIR="${KB_DIR:-$HOME/knowledge}"
NOTIF_DIR="$KB_DIR/notifications/$TARGET"

# Build filename from timestamp + slugified subject
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%S.000Z)
FILENAME_TS=$(date -u +%Y%m%dT%H%M%S)
SLUG=$(echo "$SUBJECT" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | cut -c1-40)
FILENAME="${FILENAME_TS}-${SLUG}.json"

# Create notification directory and file
mkdir -p "$NOTIF_DIR"

cat > "$NOTIF_DIR/$FILENAME" <<JSONEOF
{
  "from": "$FROM",
  "to": "$TARGET",
  "subject": $(printf '%s' "$SUBJECT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "$SUBJECT"),
  "message": $(printf '%s' "$MESSAGE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "$MESSAGE"),
  "timestamp": "$TIMESTAMP",
  "priority": "$PRIORITY"
}
JSONEOF

# Git add, commit, push
cd "$KB_DIR"
REL_PATH="notifications/$TARGET/$FILENAME"
git add "$REL_PATH"
# Sanitize subject for safe use in commit message (strip shell metacharacters)
SAFE_SUBJECT=$(echo "$SUBJECT" | tr -d '"$`\\!&|;' | cut -c1-80)
git commit -m "notify($TARGET): $SAFE_SUBJECT" --quiet 2>/dev/null

if ! git push origin HEAD --quiet 2>/dev/null; then
    # Pull-rebase and retry if push failed (concurrent KB edits)
    git pull --rebase origin master --quiet 2>/dev/null || git pull --rebase origin main --quiet 2>/dev/null || true
    if ! git push origin HEAD --quiet 2>/dev/null; then
        echo "Failed to push notification — committed locally but push failed." >&2
        exit 1
    fi
    echo "Notification sent to $TARGET: $SUBJECT (after rebase)"
else
    echo "Notification sent to $TARGET: $SUBJECT"
fi
