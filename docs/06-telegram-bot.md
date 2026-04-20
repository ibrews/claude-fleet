# Telegram & Phone Access

There are three orthogonal ways to reach your fleet from your phone. Pick the ones that fit — they don't conflict, and most users will use #1 + #2 together.

## Before You Start: Choose Your Phone-Access Model

| # | Feature | What it is | Scope |
|---|---------|------------|-------|
| 1 | **`/remote-control`** (built-in, Claude Code 2.1.80+) | Native mobile app access to any live Claude Code session. Run the slash command, open the URL on your phone. | Per-session, every machine |
| 2 | **Outbound Telegram notifications** (this doc, Part A) | "Task complete / needs your decision" pings from every machine via a notification bot. | Fleet-wide |
| 3 | **Telegram channel plugin** (this doc, Part B) | A dedicated Claude Code session that receives Telegram messages as input via `plugin:telegram@claude-plugins-official`. DM the bot with knowledge questions, get replies. | **Single machine fleet-wide** (bot tokens allow exactly one `getUpdates` poller) |

`/remote-control` is the easiest path to "drive my live session from my phone" and has no fleet-wide coordination cost. See [12-remote-control.md](./12-remote-control.md).

Parts A and B below use **different bot tokens** — keep the notification bot separate from the channel-plugin bot so the single-poller constraint in Part B doesn't starve Part A.

---

## Part A — Outbound Notifications

Telegram gives you a real-time view of what your fleet is doing without watching terminals.

### What You'll Get

Every time a Claude session finishes on any machine, you get a message:

```
✅ alpha — task complete

Refactored the auth module. All 47 tests pass. Pushed to main.
```

Status icons:
- ✅ Task completed successfully
- ❌ Error detected in the response
- ⚠️ Hit the turn limit (may need re-running)
- 🔔 Needs your decision or manual intervention

### Setup

See [../telegram/setup-bot.md](../telegram/setup-bot.md) for the step-by-step bot creation guide.

Once you have your token and chat ID, create `~/claude-fleet/fleet.env` on each machine:

```bash
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### How It Works

The `notify-human.js` script runs as a Claude Code Stop hook. When Claude finishes:

1. It reads the Stop hook payload from stdin (JSON with `stopReason` and `responseText`)
2. Picks a status icon based on the stop reason and response content
3. Sends a message to your Telegram chat via the Bot API

The script has zero dependencies — it uses only Node.js built-in `https` module.

### Fleet-Wide Summaries

The `fleet-inbox-check.sh` script also sends a Telegram summary after triggering all machines:

```
📬 Fleet Inbox Check — 14:30

✅ alpha — done
✅ beta — done
❌ gamma — failed

⚠️ Needs your attention:

🔔 beta:
MagiHuman install BLOCKED — needs 45GB, only 16GB free.

2/3 machines responded.
```

Notifications run fleet-wide: every machine can use the same bot token and chat ID to message you.

---

## Part B — Live Session Access

Two sub-options, depending on whether you want to drive a specific session or message a long-running assistant.

### For most users: `/remote-control`

Inside any Claude Code session, run:

```
/remote-control
```

It prints a URL. Open it on your phone — the live session renders inside the Claude mobile app. See [12-remote-control.md](./12-remote-control.md) for details. This is per-session and works on every fleet machine with no coordination.

### For advanced users: dedicated Telegram channel session

If you want a persistent DM-driven assistant (e.g., "ask my KB anything, from my phone, without being at a machine"), install the official Telegram channel plugin and run one long-lived session that receives messages from a bot.

```bash
claude plugin install plugin:telegram@claude-plugins-official
```

Then launch a session with the channel enabled:

```bash
cd /path/to/your/kb
claude --channels plugin:telegram@claude-plugins-official
```

Pair your Telegram bot via `/telegram:configure` and manage allowed users via `/telegram:access`. Messages you send to the bot arrive inside the session; Claude replies through the `reply` tool.

**Single-poller constraint (important):** The Telegram Bot API allows exactly one active `getUpdates` poller per bot token. That means **only one machine fleet-wide** can run `claude --channels plugin:telegram@...` for a given bot at a time. Start two and they'll fight over updates and lose messages. Pick the fleet machine with the best uptime and the canonical KB checkout.

Use a **different bot token** from your notification bot in Part A — otherwise the channel-plugin session will swallow updates that the notification bot expects.

#### Auto-launching the channel session with launchd + tmux

Because `claude --channels` is interactive (it's a TUI), you need a PTY to keep it alive at login. The common pattern is tmux inside a `launchd` agent (macOS) or a systemd user unit (Linux).

A ready-to-adapt example lives at [`examples/telegram-channel-autolaunch/`](../examples/telegram-channel-autolaunch/) with:

- `start-telegram-channel-session.sh` — spawns the session in a named tmux session, killing stale ones first
- `com.example.telegram-channel.plist` — launchd agent that runs the script at login
- `uninstall-telegram-channel-autolaunch.sh` — tears it all down

Attach to the live session with:

```bash
tmux attach -t telegram-channel
```

See the example's README for placeholder-replacement instructions.
