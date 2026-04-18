#!/usr/bin/env bash
# ~/claude-fleet/scripts/hooks/lib/tg-notify.sh
# Helper: send a Telegram message with optional inline keyboard.
#
# Usage:
#   tg_send_turn_warning <session_id> <transcript_path> <cwd> <count> <limit> <kind>
#     kind = warn | final | killed
#
# Reads bot credentials from ~/claude-fleet/fleet.env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID).
# If missing, becomes a no-op with a stderr warning — no hardcoded fallback, so a stale
# token can never leak messages to the wrong bot.

TG_ENV_FILE="${HOME}/claude-fleet/fleet.env"
if [ -f "$TG_ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$TG_ENV_FILE"
fi

tg_machine() {
    hostname -s 2>/dev/null | tr '[:upper:]' '[:lower:]'
}

# Extract the first user prompt from a transcript JSONL (up to 200 chars).
tg_first_prompt() {
    local transcript="$1"
    [ -r "$transcript" ] || { echo ""; return; }
    python3 - "$transcript" <<'PY' 2>/dev/null
import json, sys
path = sys.argv[1]
try:
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get('type') == 'user':
                msg = e.get('message') or {}
                content = msg.get('content')
                if isinstance(content, str) and content.strip():
                    print(content.strip().replace('\n', ' ')[:200])
                    sys.exit(0)
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get('type') == 'text':
                            t = (part.get('text') or '').strip()
                            if t:
                                print(t.replace('\n', ' ')[:200])
                                sys.exit(0)
            if e.get('type') == 'queue-operation' and e.get('operation') == 'enqueue':
                c = e.get('content')
                if isinstance(c, str) and len(c) > 2 and not c.startswith('{') and not c.startswith('<'):
                    print(c.replace('\n', ' ')[:200])
                    sys.exit(0)
except Exception:
    pass
PY
}

tg_html_escape() {
    python3 -c "import sys,html; print(html.escape(sys.stdin.read()), end='')"
}

# Send a Telegram message with optional inline keyboard (JSON string).
# Args: <html_text> [<reply_markup_json>]
tg_send() {
    local text="$1"
    local markup="$2"
    if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
        echo "[tg-notify] $TG_ENV_FILE missing — Telegram alert suppressed" >&2
        return 0
    fi
    local url="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
    if [ -n "$markup" ]; then
        curl -s -X POST "$url" \
            --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
            --data-urlencode "parse_mode=HTML" \
            --data-urlencode "text=${text}" \
            --data-urlencode "reply_markup=${markup}" > /dev/null 2>&1 &
    else
        curl -s -X POST "$url" \
            --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
            --data-urlencode "parse_mode=HTML" \
            --data-urlencode "text=${text}" > /dev/null 2>&1 &
    fi
}

# Build the turn-guard warning message and send it.
# Includes a trailing `<code>#sid=... #machine=...</code>` tag so the fleet-bot
# can route Telegram replies back into the right session.
tg_send_turn_warning() {
    local sid="$1" transcript="$2" cwd="$3" count="$4" limit="$5" kind="$6"

    local machine repo prompt
    machine="$(tg_machine)"
    repo="$(basename "$cwd" 2>/dev/null)"
    [ -z "$repo" ] && repo="$cwd"
    prompt="$(tg_first_prompt "$transcript")"
    [ -z "$prompt" ] && prompt="(no starting prompt found)"

    local header
    case "$kind" in
        killed)  header="🛑 <b>Turn guard killed a session</b>";;
        final)   header="🚨 <b>Turn guard — 50 turns from hard stop</b>";;
        warn|*)  header="⚠️ <b>Turn guard warning</b>";;
    esac

    local repo_esc prompt_esc
    repo_esc="$(printf '%s' "$repo"   | tg_html_escape)"
    prompt_esc="$(printf '%s' "$prompt" | tg_html_escape)"

    local text
    text="$(printf '%s\n<b>machine:</b> %s\n<b>repo:</b> %s\n<b>turns:</b> %s / %s\n<b>starting prompt:</b>\n<i>%s</i>\n<code>#sid=%s #machine=%s</code>' \
        "$header" "$machine" "$repo_esc" "$count" "$limit" "$prompt_esc" "$sid" "$machine")"

    local markup=""
    if [ "$kind" = "warn" ] || [ "$kind" = "final" ]; then
        # callback_data format: "<action>:<machine>:<sid>"
        # actions: s=stop now, u=unrestrict (+250 turns)
        markup="$(python3 - "$machine" "$sid" <<'PY'
import json, sys
machine, sid = sys.argv[1], sys.argv[2]
kb = {"inline_keyboard": [[
    {"text": "🛑 Stop Now",   "callback_data": f"s:{machine}:{sid}"},
    {"text": "🔓 Unrestrict", "callback_data": f"u:{machine}:{sid}"},
]]}
print(json.dumps(kb), end='')
PY
)"
    fi

    tg_send "$text" "$markup"
}
