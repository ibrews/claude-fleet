#!/usr/bin/env bash
# SessionEnd hook — auto-checkout this session from the presence board.
#
# Reads the stable slug written at SessionStart from ~/.cache/board-slug-<sid>,
# runs session-board.sh checkout, then removes the marker.
#
# Exit 0 always — never block session end.
set -uo pipefail
KB="$HOME/knowledge"
S="${FLEET_SCRIPTS:-$HOME/claude-fleet}/session-board.sh"

# Read stdin for session_id.
stdin_data=""
if [ -t 0 ]; then
  stdin_data=""
else
  stdin_data=$(cat 2>/dev/null || true)
fi

session_id=""
if [ -n "$stdin_data" ]; then
  session_id=$(python3 -c \
    'import sys,json; d=json.loads(sys.stdin.read()); print(d.get("session_id",""))' \
    <<< "$stdin_data" 2>/dev/null || true)
fi

[ -z "$session_id" ] && exit 0

marker="$HOME/.cache/board-slug-${session_id}"
[ -f "$marker" ] || exit 0

slug=$(cat "$marker" 2>/dev/null || true)
[ -z "$slug" ] && { rm -f "$marker"; exit 0; }

[ -x "$S" ] && "$S" checkout "$slug" 2>/dev/null || true
rm -f "$marker"

exit 0
