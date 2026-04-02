# Telegram Notifications

Telegram gives you a real-time view of what your fleet is doing without watching terminals.

## What You'll Get

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

## Setup

See [telegram/setup-bot.md](../telegram/setup-bot.md) for the step-by-step bot creation guide.

Once you have your token and chat ID, create `~/.claude/fleet.env` on each machine:

```bash
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

## How It Works

The `notify-human.js` script runs as a Claude Code Stop hook. When Claude finishes:

1. It reads the Stop hook payload from stdin (JSON with `stopReason` and `responseText`)
2. Picks a status icon based on the stop reason and response content
3. Sends a message to your Telegram chat via the Bot API

The script has zero dependencies — it uses only Node.js built-in `https` module.

## Fleet-Wide Summaries

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

## Advanced: Remote Control with ccgram

For full remote control of Claude sessions via Telegram — permission forwarding (Allow/Deny buttons), sleep mode, interactive questions — look into setting up a Telegram bot webhook handler. The basic pattern:

1. **PreToolUse hook**: When Claude wants to run a tool, send a Telegram message with Allow/Deny inline keyboard buttons
2. **Callback handler**: Listen for button clicks, write the decision to a file
3. **Hook polls the file**: The hook script waits for the decision file, reads it, returns `{"decision":"allow"}` or `{"decision":"deny"}`
4. **Sleep mode**: A flag file that, when present, auto-allows all tools without asking

This turns Telegram into a remote control panel for your fleet.
