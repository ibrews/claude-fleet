#!/usr/bin/env bash
# Fleet Inbox Trigger — Check all machines' inboxes in parallel
#
# SSHes into every machine in your fleet, runs Claude Code with a prompt
# to check and process its inbox, then sends a Telegram summary.
#
# Usage:
#   ./fleet-inbox-check.sh              # trigger all machines
#   ./fleet-inbox-check.sh alpha beta   # trigger specific machines

set -eo pipefail

CLAUDE_PROMPT='Pull the knowledge base at ~/knowledge with git pull origin master. Then read your inbox file in the inbox/ folder and act on any pending items. Mark completed items as done, commit and push changes.'

# ── Configure your fleet ─────────────────────────────────────────────
# Space-separated list of machine names (must match SSH config or Tailscale hostnames)
ALL_MACHINES="alpha beta gamma"

# Returns the SSH host for a given machine name
# Use "localhost" for the machine you're running this script from
get_host() {
  case "$1" in
    alpha) echo "localhost" ;;  # this machine
    *)     echo "$1" ;;         # SSH via Tailscale hostname
  esac
}

# Returns the claude command for a given machine
# You may need full paths if SSH doesn't load the shell profile
get_claude_cmd() {
  case "$1" in
    # macOS (Homebrew): echo "/opt/homebrew/bin/claude" ;;
    # macOS (App):      echo "$HOME/Library/Application Support/Claude/claude-code/<version>/claude.app/Contents/MacOS/claude" ;;
    # Linux:            echo "/usr/local/bin/claude" ;;
    # Windows (via SSH): echo "claude" ;;  # usually works if Node is in PATH
    *) echo "claude" ;;
  esac
}
# ─────────────────────────────────────────────────────────────────────

# Telegram config (optional — reads from .env file)
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""
for envfile in "$HOME/claude-fleet/fleet.env" "$HOME/.claude/fleet.env" "$HOME/.ccgram/.env"; do
  if [ -f "$envfile" ]; then
    TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$(grep TELEGRAM_BOT_TOKEN "$envfile" 2>/dev/null | cut -d= -f2)}"
    TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-$(grep TELEGRAM_CHAT_ID "$envfile" 2>/dev/null | cut -d= -f2)}"
  fi
done

send_telegram() {
  local msg="$1"
  if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d chat_id="$TELEGRAM_CHAT_ID" \
      -d parse_mode="HTML" \
      -d text="$msg" >/dev/null 2>&1
  fi
}

# Parse args
if [ $# -gt 0 ]; then
  TARGETS="$*"
else
  TARGETS="$ALL_MACHINES"
fi

# Push latest KB first so all machines get current inbox state
echo "[prep] Syncing knowledge base..."
KB_DIR="${HOME}/knowledge"
if [ -d "$KB_DIR/.git" ]; then
  cd "$KB_DIR"
  git add -A && git diff --cached --quiet || git commit -m "chore(inbox): pre-trigger sync" 2>/dev/null
  git push 2>/dev/null || true
  cd - >/dev/null
fi

# Trigger each machine in parallel
PIDS=""
NAMES=""
COUNT=0

for name in $TARGETS; do
  host=$(get_host "$name")
  claude_cmd=$(get_claude_cmd "$name")

  echo "[$name] Triggering inbox check..."
  LOGFILE="/tmp/inbox-check-${name}.log"

  if [ "$host" = "localhost" ]; then
    "$claude_cmd" -p "$CLAUDE_PROMPT" --max-turns 15 > "$LOGFILE" 2>&1 &
  else
    ssh -o ConnectTimeout=10 "$host" "$claude_cmd -p \"$CLAUDE_PROMPT\" --max-turns 15" > "$LOGFILE" 2>&1 &
  fi

  PIDS="$PIDS $!"
  NAMES="$NAMES $name"
  COUNT=$((COUNT + 1))
done

if [ $COUNT -eq 0 ]; then
  echo "No machines to trigger."
  exit 1
fi

echo ""
echo "Waiting for $COUNT machine(s)..."
echo ""

# Collect results
FAILED=0
RESULTS=""
i=0
for pid in $PIDS; do
  i=$((i + 1))
  name=$(echo $NAMES | cut -d' ' -f$i)
  if wait "$pid"; then
    echo "[$name] DONE — see /tmp/inbox-check-${name}.log"
    RESULTS="$RESULTS\n✅ <b>$name</b> — done"
  else
    echo "[$name] FAILED — see /tmp/inbox-check-${name}.log"
    RESULTS="$RESULTS\n❌ <b>$name</b> — failed"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "Completed: $((COUNT - FAILED))/$COUNT succeeded"

# ── Telegram summary ─────────────────────────────────────────────────

# Scan logs for items needing human attention
ATTENTION=""
for name in $TARGETS; do
  LOGFILE="/tmp/inbox-check-${name}.log"
  [ ! -f "$LOGFILE" ] && continue
  NEEDS=$(grep -i "human\|decision\|blocked\|needs.*input\|waiting.*for\|manual\|review\|pending" "$LOGFILE" 2>/dev/null | head -3)
  if [ -n "$NEEDS" ]; then
    SAFE=$(echo "$NEEDS" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g' | head -3)
    ATTENTION="$ATTENTION\n\n🔔 <b>$name</b>:\n$SAFE"
  fi
done

TIMESTAMP=$(date "+%H:%M")
TG_MSG="📬 <b>Fleet Inbox Check</b> — $TIMESTAMP
$(echo -e "$RESULTS")"

if [ -n "$ATTENTION" ]; then
  TG_MSG="$TG_MSG

⚠️ <b>Needs your attention:</b>$(echo -e "$ATTENTION")"
fi

TG_MSG="$TG_MSG

$((COUNT - FAILED))/$COUNT machines responded."

send_telegram "$TG_MSG"
echo "[telegram] Summary sent."
