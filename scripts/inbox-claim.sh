#!/usr/bin/env bash
# inbox-claim.sh — claim (or release/complete) an inbox trigger so sibling sessions stop re-flagging it.
#
# WHY: the SessionStart inbox hook (kb-inbox-check.sh) flags actionable triggers to EVERY new
# session. Without a claim, multiple sessions pile onto the same item (e.g. the CloudXR item was
# re-flagged to session after session while another was already on it). Claiming stamps the trigger
# `status: in_progress` + your DURABLE runtime pid + a timestamp; the hook then suppresses it for
# siblings — but LIVENESS-checked: if your session dies, the item auto-re-surfaces (never silently
# lost). Same lesson as the session-board durable-PID fix.
# See https://github.com/ibrews/claude-fleet/blob/main/docs/14-concurrent-sessions.md
#
# Usage:
#   inbox-claim.sh <trigger.md>           # claim   → status: in_progress (+claimed_by/pid/at)
#   inbox-claim.sh <trigger.md> done      # release → status: completed (+completed_at)
#   inbox-claim.sh <trigger.md> release   # hand back → status: pending
#
# This script never sets status: blocked — that's a deliberate, human-directed edit (see
# docs/05-inbox-system.md § Task lifecycle v2), not something claim/done/release do. If it runs
# on a trigger that WAS blocked, it clears the now-stale `blocked_on:` field so the frontmatter
# doesn't contradict itself; it never touches `tier:` or `done_when:`, which are fixed at creation.
#
# Then commit: cd ~/knowledge && git add triggers/ && git commit -m '...' && git push

set -euo pipefail
KB="${KB_ROOT:-$HOME/knowledge}"
arg="${1:?usage: inbox-claim.sh <trigger.md> [done|release]}"
verb="${2:-claim}"
f="$KB/triggers/$(basename "$arg")"
[ -f "$f" ] || { echo "no such trigger: $f" >&2; exit 1; }
MACHINE="${FLEET_MACHINE:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Durable runtime pid (same walk as session-board.sh): up the process tree to the claude agent
# runtime, NOT $PPID (the ephemeral subshell that would be dead by the time a sibling checks).
durable_pid() {
  local p="$$" cmd
  while [ "${p:-0}" -gt 1 ]; do
    cmd="$(ps -p "$p" -o command= 2>/dev/null || true)"
    case "$cmd" in *claude*--output-format*|*claude\ -p*|*claude*--print*) echo "$p"; return;; esac
    p="$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' ')"; [ -n "$p" ] || break
  done
  echo "$PPID"
}

case "$verb" in
  claim)                    newstatus="in_progress" ;;
  done|complete|completed)  newstatus="completed" ;;
  release)                  newstatus="pending" ;;
  *) echo "unknown verb: $verb (use: claim | done | release)" >&2; exit 1 ;;
esac

rt="$(durable_pid)"

# Rewrite the frontmatter in one awk pass: replace known fields if present, append the claim
# fields inside the frontmatter if missing (older triggers predate claimed_pid/claimed_at).
#
# `tier:` and `done_when:` are never touched here — they're set once at trigger creation and stay
# fixed for the trigger's life, no matter how many times it's claimed/released/completed.
# `blocked_on:` IS touched, but only to clear it: none of this script's verbs (claim/done/release)
# ever set status to "blocked" — blocking is a deliberate, human-directed edit, not something this
# script does — so if a trigger arrives here with status: blocked, it's being moved OUT of that
# state, and a stale blocked_on left behind would contradict the new status. Clearing it keeps the
# frontmatter internally consistent instead of showing e.g. "status: completed" next to a
# leftover "blocked_on: waiting on Alex to plug in the headset".
awk -v st="$newstatus" -v who="$MACHINE" -v pid="$rt" -v ts="$now" -v verb="$verb" '
  BEGIN { fm=0; ds=0; dby=0; dpid=0; dat=0; dcomp=0; origstatus="" }
  /^---[[:space:]]*$/ {
    fm++
    if (fm==2) {
      if (!ds) print "status: " st
      if (verb=="claim") {
        if (!dby)  print "claimed_by: " who
        if (!dpid) print "claimed_pid: " pid
        if (!dat)  print "claimed_at: " ts
      }
      if (verb=="done"||verb=="complete"||verb=="completed") { if (!dcomp) print "completed_at: " ts }
      print; next
    }
    print; next
  }
  fm==1 && /^status:[[:space:]]/ {
    line=$0; sub(/^status:[[:space:]]*/,"",line); split(line, parts, /[[:space:]#]/); origstatus=parts[1]
    print "status: " st; ds=1; next
  }
  fm==1 && /^blocked_on:/ {
    if (origstatus=="blocked") print "blocked_on: \"\"  # cleared by inbox-claim.sh — no longer blocked"
    else print
    next
  }
  fm==1 && /^claimed_by:/   { if (verb=="claim") { print "claimed_by: " who; dby=1 } else print; next }
  fm==1 && /^claimed_pid:/  { if (verb=="claim") { print "claimed_pid: " pid; dpid=1 } else print; next }
  fm==1 && /^claimed_at:/   { if (verb=="claim") { print "claimed_at: " ts; dat=1 } else print; next }
  fm==1 && /^completed_at:/ { if (verb=="done"||verb=="complete"||verb=="completed") { print "completed_at: " ts; dcomp=1 } else print; next }
  { print }
' "$f" > "$f.tmp" && mv "$f.tmp" "$f"

echo "$verb → $(basename "$f"): status=$newstatus (by $MACHINE, pid $rt, $now)"
