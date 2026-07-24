#!/bin/bash
# Claude Code Hook: Check KB inbox for pending items
# Called on SessionStart — pulls KB, checks inbox, injects pending items into context
#
# Output: JSON with hookSpecificOutput.additionalContext containing any pending items
# If no pending items, outputs nothing (hook is silent)

set -euo pipefail

KB_DIR="$HOME/knowledge"
MACHINE_NAME="${KB_MACHINE_NAME:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"

# Map hostnames to inbox file names
case "$MACHINE_NAME" in
    macbookpro|alexs-macbook-pro*) INBOX_FILE="inbox/alex-mbp.md" ;;
    alexs-mac-mini*|sam*)          INBOX_FILE="inbox/sam.md" ;;
    fortress|fort*)                INBOX_FILE="inbox/fort.md" ;;
    fridge|archie*)                INBOX_FILE="inbox/archie.md" ;;
    lenovo*)                       INBOX_FILE="inbox/lenovo.md" ;;
    theseus*)                      INBOX_FILE="inbox/theseus.md" ;;
    toaster*)                      INBOX_FILE="inbox/toaster.md" ;;
    *)                             INBOX_FILE="inbox/${MACHINE_NAME}.md" ;;
esac

# classify_trigger <file> → echoes: suppress | flag-pending | flag-stale | flag-review
#   suppress     = completed/done/blocked, OR in_progress with a LIVE or recent (<30m) claim
#                  → another session is on it (or it's not actionable now) → don't re-flag.
#                  `blocked` belongs here: it means "waiting on a human/hardware/a window," and
#                  nagging about it every session is noise the human can't act on mid-queue.
#                  This is WHY the state exists — see docs/05-inbox-system.md § Task lifecycle v2.
#   flag-pending = status: pending → normal actionable item.
#   flag-review  = status: review → work BELIEVED done, awaiting done_when verification or human
#                  eyes. Deliberately neither suppressed nor treated as an abandoned claim: it is
#                  surfaced distinctly so someone actually checks done_when on the real surface
#                  before it becomes "completed." Without this state, a session that finishes work
#                  must either lie (mark completed unverified) or leave a dead in_progress claim.
#   flag-stale   = in_progress/claimed but the claimer's process is GONE and the claim is >30m old
#                  → the working session died without finishing → re-surface so the item isn't lost.
# Gives the claim a LIVENESS check (a crashed claimant can't suppress an item forever) — same
# lesson as the session board's durable-PID fix.
# See intelligence/decisions/2026-06-23-claude-session-leak-load-collapse.md
classify_trigger() {
  local f="$1" status pid claimed_at ca now
  status="$(sed -n 's/^status:[[:space:]]*//p' "$f" 2>/dev/null | head -1 | awk '{print $1}')"
  case "$status" in
    completed|done|blocked|server-validated) echo suppress; return 0 ;;
    review)                                  echo flag-review; return 0 ;;
    pending|"")                              echo flag-pending; return 0 ;;
  esac
  # in_progress / claimed / other non-pending status → honor the claim, but verify liveness.
  pid="$(sed -n 's/^claimed_pid:[[:space:]]*//p' "$f" 2>/dev/null | head -1 | awk '{print $1}')"
  if [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1; then echo suppress; return 0; fi
  claimed_at="$(sed -n 's/^claimed_at:[[:space:]]*//p' "$f" 2>/dev/null | head -1 | awk '{print $1}')"
  if [ -n "$claimed_at" ]; then
    ca="$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$claimed_at" +%s 2>/dev/null || date -d "$claimed_at" +%s 2>/dev/null || echo 0)"
    now="$(date -u +%s)"
    if [ "${ca:-0}" -gt 0 ] && [ $(( now - ca )) -lt 1800 ]; then echo suppress; return 0; fi
  fi
  echo flag-stale; return 0
}

# Pull latest KB in background with a 5-second timeout — don't block session start
cd "$KB_DIR" 2>/dev/null && timeout 5 git pull --rebase origin master >/dev/null 2>&1 || true

# Check for pending items
INBOX_PATH="$KB_DIR/$INBOX_FILE"
if [ ! -f "$INBOX_PATH" ]; then
    exit 0
fi

# Extract pending items (lines starting with "- [ ]"). If a line references a trigger file
# (TRIGGER: <name>.md), DEFER it to the trigger loop below — that loop applies the claim/liveness
# check and is the single source of truth for trigger-backed items (avoids double-flagging and
# honors in-progress claims). Free-form inbox lines are flagged as-is.
PENDING=""
while IFS= read -r line; do
    [ -n "$line" ] || continue
    tref="$(printf '%s' "$line" | sed -n 's/.*TRIGGER:[[:space:]]*\([A-Za-z0-9._-]*\.md\).*/\1/p')"
    if [ -n "$tref" ] && [ -f "$KB_DIR/triggers/$tref" ]; then
        continue   # trigger-backed → handled (with claim check) by the trigger loop
    fi
    PENDING="${PENDING}
${line}"
done < <(grep -E '^[[:space:]]*- \[ \]' "$INBOX_PATH" 2>/dev/null || true)

# Also scan triggers/ directory for pending triggers targeting this machine
TRIGGER_NAME="${INBOX_FILE#inbox/}"    # e.g. "theseus.md"
TRIGGER_NAME="${TRIGGER_NAME%.md}"     # e.g. "theseus"
if [ -d "$KB_DIR/triggers" ]; then
    for f in "$KB_DIR/triggers/"*.md; do
        [ -f "$f" ] || continue
        grep -q "target:.*$TRIGGER_NAME" "$f" 2>/dev/null || continue
        # tier: auto | approve — labeled on every flagged item so a session knows, without opening
        # the file, whether it may drain the item unattended (auto) or must park the final
        # outward-facing/destructive/judgment step for a human (approve). Untagged = treat as approve.
        tier="$(sed -n 's/^tier:[[:space:]]*//p' "$f" 2>/dev/null | head -1 | awk '{print $1}')"
        tier_label=""
        [ -n "$tier" ] && tier_label=" [tier: ${tier}]"
        # done_when is required on new triggers, but pre-existing ones predate it. Rather than
        # bulk-autofilling (a generated placeholder reads as satisfied while meaning nothing —
        # the exact failure done_when prevents), flag it on the items someone actually picks up,
        # so judgment is only spent where work is really happening.
        dw_label=""
        grep -q "^done_when:" "$f" 2>/dev/null || dw_label=" ⚠ no done_when — write one (observable behavior on the real surface) BEFORE starting"
        case "$(classify_trigger "$f")" in
            flag-pending)
                PENDING="${PENDING}
- [ ] TRIGGER${tier_label}: $(basename "$f") — see triggers/$(basename "$f")${dw_label}" ;;
            flag-stale)
                PENDING="${PENDING}
- [ ] TRIGGER${tier_label} (⚠ claim abandoned — claimer process gone; verify with list_sessions, then re-claim or mark done): $(basename "$f") — see triggers/$(basename "$f")${dw_label}" ;;
            flag-review)
                PENDING="${PENDING}
- [ ] TRIGGER${tier_label} (🔍 NEEDS VERIFICATION: work believed done, awaiting done_when check — verify on the real surface before marking completed): $(basename "$f") — see triggers/$(basename "$f")${dw_label}" ;;
            *) : ;;   # suppress: completed / blocked / actively-claimed-and-live → don't nag
        esac
    done
fi

# Trim leading whitespace from PENDING
PENDING=$(echo "$PENDING" | sed '/^$/d')

if [ -z "$PENDING" ]; then
    exit 0
fi

# Count pending items
COUNT=$(echo "$PENDING" | wc -l | tr -d ' ')

# Inject into Claude's context so it knows about pending inbox items
# Using jq to properly escape the content
TODAY=$(date +%Y-%m-%d)
CONTEXT="You have ${COUNT} pending inbox item(s) in ${INBOX_FILE}. Process these items now:

${PENDING}

BEFORE you start an item that has a trigger file, CLAIM it so sibling sessions stop re-flagging it:
  $HOME/claude-fleet/inbox-claim.sh <trigger-file.md>     # sets status: in_progress + your durable pid + claimed_at
The claim is liveness-checked: if your session dies, the item auto-re-surfaces — it won't be lost.

After processing each item:
1. Mark it done: change '- [ ]' to '- [x] (${TODAY})' AND set the trigger to completed:
   $HOME/claude-fleet/inbox-claim.sh <trigger-file.md> done   (sets status: completed + completed_at)
2. Move it to the '## Done' section
3. If the task came from another machine (@sender), add a confirmation to the sender's inbox
4. Commit and push: cd ~/knowledge && git add inbox/ triggers/ && git commit -m 'chore(inbox): processed pending items' && git push"

# Output JSON with both a visible message to the user AND context for the model
python3 -c "
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
