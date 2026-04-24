#!/usr/bin/env bash
# ~/claude-fleet/scripts/hooks/turn-guard.sh
# PreToolUse hook — stops runaway sessions before they burn unbounded tokens.
#
# Install in ~/.claude/settings.json:
#   { "hooks": { "PreToolUse": [{ "hooks": [{
#       "type": "command",
#       "command": "$HOME/claude-fleet/scripts/hooks/turn-guard.sh"
#   }]}]}}
#
# What it does:
#   Counts tool calls per session using a temp file keyed by session_id.
#     WARN_TURNS  (200) → Telegram warning with [Stop Now] [Unrestrict] buttons.
#     FINAL_TURNS (450) → second warning with the same buttons.
#     HANDOFF    (490) → blocks one call with a "write a handoff prompt" reason.
#     MAX_TURNS   (500) → blocks all further tool calls with a Telegram kill notice.
#
# Per-session overrides (written by the fleet-bot over SSH when a button is pressed):
#   /tmp/tg-<sid>.max    → replace MAX_TURNS for this session (e.g. 750 = +250).
#   /tmp/tg-<sid>.stop   → block immediately with "stopped by operator".

WARN_TURNS=200
FINAL_TURNS=450
HANDOFF_TURNS_BEFORE_MAX=10
MAX_TURNS=500

# shellcheck source=/dev/null
. "${HOME}/claude-fleet/scripts/hooks/lib/tg-notify.sh"

INPUT=$(cat)
parse_field() {
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$1','') or '')" 2>/dev/null <<<"$INPUT"
}
SESSION_ID=$(parse_field session_id)
TRANSCRIPT=$(parse_field transcript_path)
CWD=$(parse_field cwd)
SESSION_ID="${SESSION_ID:-unknown}"
[ -z "$CWD" ] && CWD="$(pwd)"

COUNTER_FILE="/tmp/tg-${SESSION_ID}"
STOP_FILE="/tmp/tg-${SESSION_ID}.stop"
MAX_FILE="/tmp/tg-${SESSION_ID}.max"
HANDOFF_FLAG="/tmp/tg-${SESSION_ID}.handoff-delivered"

# Honor operator "Stop Now" press.
if [ -f "$STOP_FILE" ]; then
    echo '{"decision":"block","reason":"Turn guard: operator stopped this session from Telegram. Use /clear to start fresh."}'
    exit 2
fi

# Honor operator "Unrestrict" override.
if [ -f "$MAX_FILE" ]; then
    OVERRIDE=$(cat "$MAX_FILE" 2>/dev/null)
    if [[ "$OVERRIDE" =~ ^[0-9]+$ ]]; then
        MAX_TURNS="$OVERRIDE"
        FINAL_TURNS=$((MAX_TURNS - 50))
        # After an unrestrict, re-arm handoff delivery for the new cap.
        rm -f "$HANDOFF_FLAG"
    fi
fi
HANDOFF_TURNS=$((MAX_TURNS - HANDOFF_TURNS_BEFORE_MAX))

PREV=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
COUNT=$((PREV + 1))
echo "$COUNT" > "$COUNTER_FILE"

# ~10 turns before the hard stop, block a single tool call with a reason that
# instructs Claude to write a handoff prompt. The remaining turns let it finish.
if [ "$COUNT" -ge "$HANDOFF_TURNS" ] && [ "$COUNT" -lt "$MAX_TURNS" ] && [ ! -f "$HANDOFF_FLAG" ]; then
    touch "$HANDOFF_FLAG"
    REMAINING=$((MAX_TURNS - COUNT))
    HANDOFF_MSG="Turn guard: you have ${REMAINING} tool calls left before this session is force-stopped at ${MAX_TURNS}. Before doing anything else, write a handoff prompt so a future session can resume cleanly. Save it to HANDOFF_PROMPT.md in the current repo root if this is a project repo, otherwise to \$HOME/claude-fleet/triggers/handoff-${SESSION_ID:0:8}.md. Include: (1) goal of the current task, (2) what you've done so far with file paths and line numbers, (3) what's next in order, (4) any open questions or blockers, (5) commands/tests to verify progress. Then continue your task with whatever turns remain."
    python3 -c "import json,sys; print(json.dumps({'decision':'block','reason':sys.argv[1]}))" "$HANDOFF_MSG"
    exit 2
fi

if [ "$COUNT" -ge "$MAX_TURNS" ]; then
    tg_send_turn_warning "$SESSION_ID" "$TRANSCRIPT" "$CWD" "$COUNT" "$MAX_TURNS" killed
    echo "{\"decision\":\"block\",\"reason\":\"Turn guard: $COUNT tool calls in this session (limit: $MAX_TURNS). Session stopped to prevent runaway cost. Use /clear to start fresh.\"}"
    exit 2
fi

if [ "$COUNT" -eq "$WARN_TURNS" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARN session=$SESSION_ID count=$COUNT" >> /tmp/turn-guard.log
    tg_send_turn_warning "$SESSION_ID" "$TRANSCRIPT" "$CWD" "$COUNT" "$MAX_TURNS" warn
fi

if [ "$COUNT" -eq "$FINAL_TURNS" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FINAL session=$SESSION_ID count=$COUNT" >> /tmp/turn-guard.log
    tg_send_turn_warning "$SESSION_ID" "$TRANSCRIPT" "$CWD" "$COUNT" "$MAX_TURNS" final
fi

exit 0
