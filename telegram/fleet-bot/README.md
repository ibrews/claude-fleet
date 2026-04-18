# fleet-bot

A Telegram relay for a Claude Code fleet. Runs as a single persistent process on your always-on gateway machine and gives you two capabilities from your phone:

1. **Interactive turn-guard.** When [turn-guard.sh](../../scripts/hooks/turn-guard.sh) fires at 200 / 450 / 500 tool calls, the Telegram notification carries `[🛑 Stop Now]` and `[🔓 Unrestrict]` buttons. Tap to SSH into the right machine and mutate per-session state files (`/tmp/tg-<sid>.stop`, `/tmp/tg-<sid>.max`).
2. **Reply-to-session routing.** Every turn-guard message ends with a `<code>#sid=<uuid> #machine=<hostname></code>` tag. Reply to any such message from Telegram and the bot runs `claude --resume <sid> -p "<your text>"` on the right machine. If the target session is live (JSONL modified in the last 30s), the message is queued to `/tmp/tg-queue-<sid>.txt` instead of racing a concurrent `claude --resume`.

## Why a dedicated bot

Telegram allows only one `getUpdates` long-poller per bot token. If you're already running the [ccgram](https://github.com/jsayubi/ccgram) per-session bot or the Claude Code telegram MCP plugin, they claim that lease. Create a **second** bot via @BotFather for fleet-bot so the two don't collide (409 Conflict errors).

## Setup

1. Create a new bot with @BotFather, save the token.
2. Write `~/claude-fleet/fleet.env`:
   ```
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   ```
3. Copy `machines.example.json` → `machines.json` and edit with your Tailscale IPs / SSH users. The key names must match `hostname -s | tr '[:upper:]' '[:lower:]'` on each box (that's what turn-guard embeds in `#machine=` tags).
4. Run `./install.sh`. On macOS it installs a `com.claudefleet.bot` launchd agent that runs `bot.mjs` with `KeepAlive=true`.

## Verify

```bash
launchctl list | grep com.claudefleet.bot
tail -f /tmp/fleet-bot.log
```

Send `/ping` to the bot in Telegram — you should get `pong`.

## Callback actions

| callback_data | action |
|---|---|
| `s:<machine>:<sid>` | `touch /tmp/tg-<sid>.stop` on `<machine>` |
| `u:<machine>:<sid>` | Raise `/tmp/tg-<sid>.max` by 250 on `<machine>` |
| `k:<machine>:<sid>` | Resume session with `"Great, keep going!"` |

`<machine>` is looked up in `machines.json`; if `host` is `localhost`, the command runs locally instead of over SSH.

## Ops notes

- **Read-only fallback.** `turn-guard.sh` sources `lib/tg-notify.sh` which no-ops if `fleet.env` is missing — no hardcoded token, so a stale bot token can't leak messages to the wrong chat.
- **Tag format.** `#sid=<base64url>` (only `[A-Za-z0-9_-]` allowed) and `#machine=<hostname>` (`[A-Za-z0-9_.-]`). Other hooks in your fleet can embed the same tags if you want replies-from-Telegram to route for their messages too.
- **Unrestrict = current + 250, not unlimited.** Each press buys 250 more turns with a fresh warning 50 turns before the new cap. Repeatable but never silent.
