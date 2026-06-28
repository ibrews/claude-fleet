#!/usr/bin/env bash
# SessionStart hook — surface the concurrent-session presence board so every
# new session sees who's holding shared singletons BEFORE it acts, AND
# auto-registers this session with a stable slug so it's visible immediately.
#
# Board + protocol: ~/knowledge/sessions/README.md
# Never blocks session start: any problem → silent exit 0.
set -uo pipefail
KB="$HOME/knowledge"
S="${FLEET_SCRIPTS:-$HOME/claude-fleet}/session-board.sh"
ACTIVE="$KB/sessions/active"
[ -x "$S" ] || exit 0   # board not installed → no-op

# ── Parse stdin JSON for session_id + cwd ─────────────────────────────────
# Read stdin once; handle empty or non-JSON gracefully.
stdin_data=""
if [ -t 0 ]; then
  stdin_data=""
else
  stdin_data=$(cat 2>/dev/null || true)
fi

session_id=""
cwd_val=""
if [ -n "$stdin_data" ]; then
  session_id=$(python3 -c \
    'import sys,json; d=json.loads(sys.stdin.read()); print(d.get("session_id",""))' \
    <<< "$stdin_data" 2>/dev/null || true)
  cwd_val=$(python3 -c \
    'import sys,json; d=json.loads(sys.stdin.read()); print(d.get("cwd",""))' \
    <<< "$stdin_data" 2>/dev/null || true)
fi

# ── Compute slug + write marker ────────────────────────────────────────────
MACHINE="${FLEET_MACHINE:-$(hostname -s 2>/dev/null || echo unknown)}"
AUTO_SLUG=""

if [ -n "$session_id" ]; then
  # Derive short id (first 8 chars) and sanitized cwd basename.
  short="${session_id:0:8}"
  cwdbase=""
  if [ -n "$cwd_val" ]; then
    cwdbase=$(basename "$cwd_val" 2>/dev/null | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | sed 's/-\+/-/g' | sed 's/^-//;s/-$//')
  fi
  [ -z "$cwdbase" ] && cwdbase="session"

  AUTO_SLUG="${cwdbase}-${short}"

  # Write marker so SessionEnd can read the same slug without re-deriving.
  mkdir -p "$HOME/.cache"
  echo "$AUTO_SLUG" > "$HOME/.cache/board-slug-${session_id}"

  # Idempotent checkin: only create entry if it doesn't already exist.
  board_file="$ACTIVE/${MACHINE}-${AUTO_SLUG}.md"
  if [ ! -f "$board_file" ]; then
    "$S" checkin "$AUTO_SLUG" -S starting \
      -w "session in ${cwdbase} — details pending" 2>/dev/null || true
  fi
fi

# ── Print board ────────────────────────────────────────────────────────────
shopt -s nullglob
entries=("$ACTIVE"/*.md)
n=${#entries[@]}

if [ "$n" -eq 0 ]; then
  echo "[session-board] No other sessions checked in. If you'll hold a shared singleton (UE build engine / AVP / sim), check in: $S checkin <slug> -c \"<singleton>\""
else
  echo "[session-board] $n session(s) active — CHECK before grabbing a shared singleton (build engine / device / sim):"
  echo
  "$S" board || true
fi

# ── Announce slug to the model ─────────────────────────────────────────────
if [ -n "$AUTO_SLUG" ]; then
  echo
  echo "📋 You're auto-registered on the board as ${MACHINE}-${AUTO_SLUG}. Add detail with: session-board.sh heartbeat ${AUTO_SLUG} -S <status> -w \"<what you're doing>\" (and -c \"<singletons>\" if you hold any). Do NOT create a new slug."
else
  echo "Announce your own work:  $S checkin <slug> -s <software> -c \"<singletons>\" -S building -e <eta>"
  echo "Heartbeat at checkpoints; checkout when done.  Protocol: $KB/sessions/README.md"
fi

exit 0
