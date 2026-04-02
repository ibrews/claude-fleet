#!/bin/bash
# Claude Code SessionStart Hook: Check inbox for pending items
#
# Pulls the shared knowledge base, checks this machine's inbox file,
# and injects any pending items into Claude's context so they get
# processed automatically before anything else.
#
# Install: Add to ~/.claude/settings.json under hooks.SessionStart
# Output: JSON with additionalContext (consumed by Claude Code)

set -euo pipefail

# Where your shared knowledge base is cloned
KB_DIR="${KB_DIR:-$HOME/.claude/knowledge}"

# Machine name — used to find the right inbox file
# Override with KB_MACHINE_NAME env var, or it auto-detects from hostname
MACHINE_NAME="${KB_MACHINE_NAME:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"

# Map hostnames to inbox filenames
# Customize this for your fleet — add your machine hostnames here
case "$MACHINE_NAME" in
    # Example mappings (uncomment and edit):
    # my-macbook*) INBOX_FILE="inbox/laptop.md" ;;
    # my-server*)  INBOX_FILE="inbox/server.md" ;;
    # my-desktop*) INBOX_FILE="inbox/desktop.md" ;;
    *)           INBOX_FILE="inbox/${MACHINE_NAME}.md" ;;
esac

# Pull latest KB with a 5-second timeout — don't block session start
cd "$KB_DIR" 2>/dev/null && timeout 5 git pull --rebase origin master >/dev/null 2>&1 || true

# Check for pending items
INBOX_PATH="$KB_DIR/$INBOX_FILE"
if [ ! -f "$INBOX_PATH" ]; then
    exit 0
fi

# Extract pending items (lines starting with "- [ ]")
PENDING=$(grep -E '^\s*- \[ \]' "$INBOX_PATH" 2>/dev/null || true)

if [ -z "$PENDING" ]; then
    exit 0
fi

# Count pending items
COUNT=$(echo "$PENDING" | wc -l | tr -d ' ')

# Build the context that will be injected into Claude's session
TODAY=$(date +%Y-%m-%d)
CONTEXT="You have ${COUNT} pending inbox item(s) in ${INBOX_FILE}. Process these items now:

${PENDING}

After processing each item:
1. Mark it done: change '- [ ]' to '- [x] (${TODAY})'
2. Move it to the '## Done' section
3. If the task came from another machine (@sender), add a confirmation to the sender's inbox
4. Commit and push: cd $KB_DIR && git add inbox/ && git commit -m 'chore(inbox): processed pending items' && git push"

# Output JSON that Claude Code's hook system understands
# - systemMessage: shown to the user in the terminal
# - additionalContext: injected into Claude's context window
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")
if [ -z "$PY" ]; then
    exit 0
fi

$PY -c "
import json, sys
context = sys.stdin.read()
print(json.dumps({
    'systemMessage': '📬 ${COUNT} pending inbox item(s) found — reviewing before starting.',
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': 'IMPORTANT: Before doing ANYTHING else, process these inbox items FIRST. Tell the user you are reviewing their inbox, then process each item. Do not wait for the user to ask.\n\n' + context
    }
}))
" <<< "$CONTEXT"
