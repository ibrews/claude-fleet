# Setting Up Your Telegram Bot

> **Heads up:** This guide covers creating a bot for **outbound fleet notifications** (and, optionally, the ccgram-style permission-forwarding channel). If what you actually want is "drive a live Claude Code session from my phone," the built-in `/remote-control` slash command is usually the better fit — no bot required. See [../docs/12-remote-control.md](../docs/12-remote-control.md) and the chooser table in [../docs/06-telegram-bot.md](../docs/06-telegram-bot.md).

## 1. Create the Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a display name (e.g., "My Fleet Bot")
4. Choose a username (e.g., `my_fleet_bot`)
5. BotFather will give you a **token** — save it

## 2. Get Your Chat ID

1. Search for **@userinfobot** on Telegram
2. Send it any message
3. It replies with your **chat ID** — save it

## 3. Test It

```bash
curl -s -X POST "https://api.telegram.org/bot<YOUR_TOKEN>/sendMessage" \
  -d chat_id="<YOUR_CHAT_ID>" \
  -d text="Hello from my fleet!"
```

You should receive the message in Telegram.

## 4. Store Credentials

Create `~/claude-fleet/fleet.env`:

```bash
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

The `notify-human.js` script and `fleet-inbox-check.sh` will read from this file automatically.

## 5. Optional: Permission Forwarding via ccgram

If you want Telegram to act as an approval channel for tool calls (beyond plain notifications), ccgram adds:

- **Permission forwarding**: Get Allow/Deny buttons in Telegram when Claude wants to run a command
- **Sleep mode**: `/sleep` to auto-approve all tool calls, `/wake` to re-enable approval
- **Interactive questions**: Claude's questions forwarded to Telegram with clickable answers

See [@anthropic-ai/ccgram](https://www.npmjs.com/package/@anthropic-ai/ccgram) (or build your own — the Telegram Bot API is straightforward).

Note: for "I just want to read and type into my session from my phone," you probably don't need ccgram — run `/remote-control` inside the session and open the URL in the Claude mobile app. See [../docs/12-remote-control.md](../docs/12-remote-control.md).
