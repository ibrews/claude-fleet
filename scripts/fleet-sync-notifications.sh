#!/bin/bash
# Fast notification sync — runs via cron every 60 seconds.
# Pulls KB, checks for notifications addressed to this machine, stages them locally.
#
# IMPORTANT: Set FLEET_MACHINE_NAME in your environment or crontab, e.g.:
#   * * * * * FLEET_MACHINE_NAME=alpha ~/claude-fleet/fleet-sync-notifications.sh

MACHINE_NAME="${FLEET_MACHINE_NAME:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
KB_DIR="$HOME/knowledge"
NOTIF_DIR="$KB_DIR/notifications/$MACHINE_NAME"
STAGING_DIR="/tmp/fleet-pending"
LOCK_FILE="/tmp/fleet-sync.lock"

# Prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
    # macOS stat uses -f %m, Linux uses -c %Y
    LOCK_AGE=$(( $(date +%s) - $(stat -f %m "$LOCK_FILE" 2>/dev/null || stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
    if [ "$LOCK_AGE" -lt 60 ]; then
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi
touch "$LOCK_FILE"
trap "rm -f '$LOCK_FILE'" EXIT

# Quick git pull (quiet, fast-forward only)
cd "$KB_DIR" || exit 1
git fetch origin master --quiet 2>/dev/null || git fetch origin main --quiet 2>/dev/null
git merge --ff-only FETCH_HEAD --quiet 2>/dev/null

# Check for notification files
if [ -d "$NOTIF_DIR" ]; then
    FOUND=false
    for f in "$NOTIF_DIR"/*.json; do
        [ -f "$f" ] || continue
        FOUND=true

        # Stage locally for the hook to pick up
        mkdir -p "$STAGING_DIR"
        cp "$f" "$STAGING_DIR/"

        # Remove from KB
        git rm "$f" --quiet 2>/dev/null
    done

    # If we removed any notifications, commit and push
    if [ "$FOUND" = true ] && ! git diff --cached --quiet 2>/dev/null; then
        git commit -m "chore(notifications): delivered to $MACHINE_NAME" --quiet 2>/dev/null
        git push origin HEAD --quiet 2>/dev/null
    fi
fi
