#!/usr/bin/env bash
# tg-mode — terminal control for the Telegram channel's sleep / limitless modes.
#
# Writes the SAME flag files the /sleep, /wake and /limitless bot commands use,
# so you can toggle from a terminal as well as from your phone. Both surfaces
# stay in sync because they share state on disk.
#
#   tg-mode sleep [8h|30m]   put the bot to sleep (queue inbound, don't wake Claude)
#   tg-mode wake             wake the bot (stop queueing; next message delivers live)
#   tg-mode limitless [8h]   bypass the turn-guard tool-call cap (optionally for a while)
#   tg-mode limited          re-arm the turn-guard (limitless OFF)
#   tg-mode status           show current modes
#
# Note: `wake` here removes the sleep flag so new messages deliver normally, but
# it cannot REPLAY messages already queued while asleep — only the running bot
# process can emit those. To flush the queue, send /wake from Telegram.
#
# Flag files:
#   sleep:     ~/.claude/channels/telegram/sleep.json
#   queue:     ~/.claude/channels/telegram/queue.jsonl
#   limitless: ~/.claude/limitless.json   (also read by ~/.claude/hooks/turn-guard.sh)

set -euo pipefail

STATE_DIR="${TELEGRAM_STATE_DIR:-$HOME/.claude/channels/telegram}"
SLEEP_FILE="$STATE_DIR/sleep.json"
QUEUE_FILE="$STATE_DIR/queue.jsonl"
LIMITLESS_FILE="$HOME/.claude/limitless.json"

# Write a {enabled, enabledAt, expiresAt} flag file. $1=path, $2=duration ("8h"/"30m"/"").
write_flag() {
    local path="$1" dur="${2:-}"
    mkdir -p "$(dirname "$path")"
    python3 - "$path" "$dur" <<'PY'
import json, sys, re
from datetime import datetime, timedelta, timezone
path, dur = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "").strip().lower()
expires = None
if dur:
    m = re.match(r'^(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)?$', dur)
    if not m or int(m.group(1)) <= 0:
        sys.stderr.write(f"bad duration: {dur!r} (use e.g. 8h or 30m)\n"); sys.exit(2)
    n = int(m.group(1)); unit = (m.group(2) or 'h').lower()
    delta = timedelta(minutes=n) if unit.startswith('m') else timedelta(hours=n)
    expires = (datetime.now(timezone.utc) + delta).isoformat().replace('+00:00', 'Z')
json.dump({"enabled": True, "enabledAt": datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
           "expiresAt": expires}, open(path, 'w'), indent=2)
print("until " + expires if expires else "indefinitely")
PY
}

flag_state() {  # prints "ON (...)" / "OFF" for a flag file
    local path="$1"
    python3 - "$path" <<'PY'
import json, sys, time
from datetime import datetime
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("OFF"); sys.exit()
if not d.get("enabled"):
    print("OFF"); sys.exit()
exp = d.get("expiresAt")
if exp:
    try:
        t = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        if t.timestamp() <= time.time():
            print("OFF (expired)"); sys.exit()
        print(f"ON (until {exp})"); sys.exit()
    except Exception:
        pass
print("ON (indefinite)")
PY
}

cmd="${1:-status}"
case "$cmd" in
    sleep)
        when=$(write_flag "$SLEEP_FILE" "${2:-}")
        echo "💤 Sleep mode ON $when — inbound messages queue instead of waking Claude. 'tg-mode wake' or /wake to resume."
        ;;
    wake)
        rm -f "$SLEEP_FILE"
        depth=0; [ -f "$QUEUE_FILE" ] && depth=$(grep -c . "$QUEUE_FILE" 2>/dev/null || echo 0)
        if [ "$depth" -gt 0 ]; then
            echo "☀️ Sleep OFF. $depth message(s) are still queued — send /wake from Telegram to replay them (only the bot can emit them)."
        else
            echo "☀️ Sleep OFF — messages deliver normally."
        fi
        ;;
    limitless)
        when=$(write_flag "$LIMITLESS_FILE" "${2:-}")
        echo "♾️  Limitless ON $when — turn-guard tool-call cap bypassed. 'tg-mode limited' or /limitless off to re-arm."
        echo "    (Only lifts the local turn-guard; cannot override Anthropic account usage limits.)"
        ;;
    limited|limit|nolimitless)
        rm -f "$LIMITLESS_FILE"
        echo "🛑 Limitless OFF — turn-guard re-armed."
        ;;
    status)
        echo "Telegram channel modes:"
        echo "  sleep:     $(flag_state "$SLEEP_FILE")"
        echo "  limitless: $(flag_state "$LIMITLESS_FILE")"
        depth=0; [ -f "$QUEUE_FILE" ] && depth=$(grep -c . "$QUEUE_FILE" 2>/dev/null || echo 0)
        echo "  queued:    $depth message(s)"
        # Claude usage, if the statusline bridge has sampled it (also via /usage on the bot).
        if [ -f "$HOME/.claude/usage-state.json" ]; then
            python3 - "$HOME/.claude/usage-state.json" <<'PY'
import json, sys, datetime
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit()
rl = d.get("rate_limits") or {}
def fmt(key, label):
    v = rl.get(key) or {}
    p = v.get("used_percentage")
    if p is None:
        return None
    s = f"  {label}: {round(p)}% used"
    r = v.get("resets_at")
    if r:
        s += " — resets " + datetime.datetime.fromtimestamp(float(r)).strftime("%a %I:%M %p").replace(" 0", " ")
    return s
out = [x for x in (fmt("five_hour", "5h window"), fmt("seven_day", "weekly")) if x]
if out:
    print(f"Claude usage (sampled {d.get('updatedAt', '?')}):")
    print("\n".join(out))
PY
        fi
        ;;
    *)
        echo "Usage: tg-mode {sleep [8h|30m] | wake | limitless [8h] | limited | status}" >&2
        exit 1
        ;;
esac
