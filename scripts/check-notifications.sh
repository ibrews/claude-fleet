#!/bin/bash
# PostToolUse hook: check for mid-session fleet notifications.
# Designed to be FAST — only checks a local staging dir, no git operations.
# The heavy lifting (git pull) is done by fleet-sync-notifications.sh via cron.

PENDING_DIR="/tmp/fleet-pending"
THROTTLE_FILE="/tmp/fleet-notif-last-check"
THROTTLE_SECONDS=10

# Throttle: don't check more than once every N seconds
if [ -f "$THROTTLE_FILE" ]; then
    LAST_CHECK=$(stat -f %m "$THROTTLE_FILE" 2>/dev/null || stat -c %Y "$THROTTLE_FILE" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    ELAPSED=$(( NOW - LAST_CHECK ))
    if [ "$ELAPSED" -lt "$THROTTLE_SECONDS" ]; then
        exit 0
    fi
fi
touch "$THROTTLE_FILE"

# Check for pending notifications
shopt -s nullglob
NOTIF_FILES=("$PENDING_DIR"/*.json)
shopt -u nullglob

if [ ${#NOTIF_FILES[@]} -eq 0 ]; then
    exit 0
fi

# Detect Python — prefer python3, fall back to python
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")

if [ -z "$PY" ]; then
    # No Python available — output minimal JSON without it
    COUNT=${#NOTIF_FILES[@]}
    CONTEXT="--- FLEET NOTIFICATION (${COUNT} message(s)) ---\nCheck /tmp/fleet-pending/ for details.\n--- END FLEET NOTIFICATION ---\nAcknowledge these notifications to the user and take any appropriate action."
    # Clean up files
    for f in "${NOTIF_FILES[@]}"; do rm -f "$f"; done
    printf '{"hookSpecificOutput":{"additionalContext":"%s"}}' "$CONTEXT"
    exit 0
fi

# Build context from all pending notifications using Python for proper JSON
"$PY" - "${NOTIF_FILES[@]}" <<'PYEOF'
import json, sys, os

files = sys.argv[1:]
messages = []
for f in files:
    try:
        with open(f) as fh:
            d = json.load(fh)
        icon = "\U0001f6a8" if d.get("priority") == "urgent" else "\U0001f4ec"
        msg = f'{icon} From {d.get("from", "unknown")}: {d.get("subject", "")}\n{d.get("message", "")}'
        messages.append(msg)
        os.unlink(f)
    except Exception:
        pass

if messages:
    count = len(messages)
    body = "\n\n".join(messages)
    context = f"--- FLEET NOTIFICATION ({count} message(s)) ---\n{body}\n--- END FLEET NOTIFICATION ---\nAcknowledge these notifications to the user and take any appropriate action."
    output = {"hookSpecificOutput": {"additionalContext": context}}
    print(json.dumps(output))
PYEOF
