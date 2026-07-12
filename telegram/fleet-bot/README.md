# fleet-bot

A Telegram relay for a Claude Code fleet. Runs as a single persistent process on your always-on gateway machine and gives you these capabilities from your phone:

1. **Interactive turn-guard.** When [turn-guard.sh](../../scripts/hooks/turn-guard.sh) fires at 200 / 450 / 500 tool calls, the Telegram notification carries `[🛑 Stop Now]` and `[🔓 Unrestrict]` buttons. Tap to SSH into the right machine and mutate per-session state files (`/tmp/tg-<sid>.stop`, `/tmp/tg-<sid>.max`).
2. **Session bus bridge** (optional — see [docs/16-session-bus.md](../../docs/16-session-bus.md)). Any session can `fleet-bus-client.js send --to human` to reach you here — e.g. wrapping up ambiguous work and wanting a nudge before it actually stops.
3. **Reply-to-session routing, bus-first.** Every turn-guard message (and every bus `--to human` relay) ends with a `<code>#sid=<uuid> #machine=<hostname></code>` tag. Reply to any such message and fleet-bot checks whether that session currently has a **live fleet-bus listener** — if so, the reply delivers **instantly through the bus** (this also reaches Windows machines, which the SSH path below can't). Otherwise it falls back to `claude --resume <sid> -p "<your text>"` on the target machine over SSH. If the target session is live but has no bus listener armed, the message is queued to `/tmp/tg-queue-<sid>.txt` instead of racing a concurrent `claude --resume`.
4. **Direct commands** (no reply needed): `/sessions` — everyone currently listening on the fleet bus. `/msg <machine> <text>` — bus-message any machine directly.

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
5. **Optional, for bus-aware routing + `/sessions` + `/msg`:** set `FLEET_BUS_URL` (default `http://localhost:4100`) and `FLEET_BUS_TOKEN` if your [session bus server](../../docs/16-session-bus.md) requires one. Without these, fleet-bot still works exactly as before — turn-guard buttons and SSH-only reply routing.

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
| `k:<machine>:<sid>` | Resume session with `"Great, keep going!"` — bus-first if the session is listening, else SSH resume |

`<machine>` is looked up in `machines.json`; if `host` is `localhost`, the command runs locally instead of over SSH.

## Ops notes

- **Read-only fallback.** `turn-guard.sh` sources `lib/tg-notify.sh` which no-ops if `fleet.env` is missing — no hardcoded token, so a stale bot token can't leak messages to the wrong chat.
- **Tag format.** `#sid=<base64url>` (only `[A-Za-z0-9_-]` allowed) and `#machine=<hostname>` (`[A-Za-z0-9_.-]`). Other hooks in your fleet can embed the same tags if you want replies-from-Telegram to route for their messages too.
- **Unrestrict = current + 250, not unlimited.** Each press buys 250 more turns with a fresh warning 50 turns before the new cap. Repeatable but never silent.
