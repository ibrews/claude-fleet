#!/usr/bin/env bash
# rate-limit-autosleep.sh — StopFailure hook.
#
# When any session fails with a rate limit (account-wide, so it affects the
# Telegram channel session too), flip the channel into sleep mode so inbound
# messages queue instead of piling onto a blocked Claude, and notify the
# operator ONCE via the channel bot. Sleep auto-expires at the 5h-window reset
# time if ~/.claude/usage-state.json knows it (statusline bridge), else in 1h.
# /wake (or `tg-mode wake`) overrides at any time.
#
# Registered under hooks.StopFailure in ~/.claude/settings.json.

INPUT=$(cat)
# Defensive match: the StopFailure payload carries error_type "rate_limit";
# substring-match the whole payload so a field rename doesn't silently kill us.
# Worst case on a false positive: one notification + an auto-expiring sleep.
case "$INPUT" in
    *rate_limit*|*rate-limit*) ;;
    *) exit 0 ;;
esac

STATE_DIR="${TELEGRAM_STATE_DIR:-$HOME/.claude/channels/telegram}"
SLEEP_FILE="$STATE_DIR/sleep.json"
USAGE_FILE="$HOME/.claude/usage-state.json"
[ -d "$STATE_DIR" ] || exit 0   # no telegram channel on this machine

# Already sleeping → nothing to do. This also throttles the notification when
# several blocked sessions fire StopFailure in quick succession.
if python3 - "$SLEEP_FILE" <<'PY'
import json, sys, time
from datetime import datetime
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
if not d.get("enabled"):
    sys.exit(1)
exp = d.get("expiresAt")
if exp:
    try:
        t = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        if t.timestamp() <= time.time():
            sys.exit(1)
    except Exception:
        pass
sys.exit(0)
PY
then
    exit 0
fi

# Write sleep.json with expiry = 5h-window reset (if known and future) else +1h.
WHEN=$(python3 - "$USAGE_FILE" "$SLEEP_FILE" <<'PY'
import json, sys, time
from datetime import datetime, timezone, timedelta
usage_p, sleep_p = sys.argv[1], sys.argv[2]
exp = None
try:
    u = json.load(open(usage_p))
    r = ((u.get("rate_limits") or {}).get("five_hour") or {}).get("resets_at")
    if r and float(r) > time.time():
        exp = datetime.fromtimestamp(float(r), timezone.utc)
except Exception:
    pass
if exp is None:
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
json.dump(
    {"enabled": True,
     "enabledAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
     "expiresAt": exp.isoformat().replace("+00:00", "Z"),
     "reason": "auto: rate limit (StopFailure hook)"},
    open(sleep_p, "w"), indent=2)
print(exp.astimezone().strftime("%a %-I:%M %p"))
PY
)

# Test seam: TG_AUTOSLEEP_DRYRUN=1 skips the Telegram send.
if [ -n "${TG_AUTOSLEEP_DRYRUN:-}" ]; then
    echo "dryrun: sleep.json written, would notify (until $WHEN)"
    exit 0
fi

TOKEN=$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$STATE_DIR/.env" 2>/dev/null | head -1)
[ -z "$TOKEN" ] && exit 0
CHATS=$(python3 -c "import json,sys; print('\n'.join(json.load(open(sys.argv[1])).get('allowFrom', [])))" "$STATE_DIR/access.json" 2>/dev/null)
for c in $CHATS; do
    curl -s --max-time 5 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
        -d chat_id="$c" \
        --data-urlencode text="💤 Claude hit a usage limit — Telegram channel is sleeping until ~${WHEN}. Messages will queue; send /wake to override." \
        >/dev/null || true
done
exit 0
