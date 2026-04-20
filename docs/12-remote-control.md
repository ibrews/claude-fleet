# Remote Control — Drive a Session From Your Phone

`/remote-control` is a built-in slash command in Claude Code 2.1.80+. It lets you mirror any live Claude Code session into the Claude mobile app so you can read context and send messages from your phone while the session keeps running on your machine.

## What It Is

- **Built in.** Nothing to install — the slash command ships with Claude Code.
- **Per-session.** Each invocation makes a URL tied to that single session. No global state.
- **Zero fleet coordination.** Every machine in your fleet can use it independently, at the same time, with no conflicts.
- **Native rendering.** The URL opens inside the Claude mobile app and renders like a native session — not a web terminal.

## How To Use

1. Inside any Claude Code session on any fleet machine, run:

   ```
   /remote-control
   ```

2. Claude prints a URL. Open it on your phone (any method: AirDrop, Messages, a QR code, copy-paste).
3. The URL opens in the Claude mobile app and attaches to the live session. Keep typing on your desktop or on your phone — both stay in sync.
4. When you're done, just close the mobile session. The desktop session continues.

## When To Use This vs The Telegram Channel Plugin

| Situation | Use |
|-----------|-----|
| "I started a session, now I need to step away and keep working from my phone" | `/remote-control` |
| "I want to reach a long-running KB-aware assistant by DM, with no machine in front of me" | Telegram channel plugin (see [06-telegram-bot.md](./06-telegram-bot.md#part-b--live-session-access)) |
| "Multiple fleet machines, multiple phone-accessible sessions at once" | `/remote-control` (the channel plugin is one machine only) |
| "I want replies to arrive in a group chat I can share with teammates" | Telegram channel plugin |

For most "phone access to my work" needs, `/remote-control` is the right answer. The Telegram channel plugin is a specialized tool for the DM-driven-assistant pattern.

## Security

The URL is privileged: anyone who opens it can type into your live Claude Code session, which typically has full tool access on your machine. Treat it like an SSH key.

- **Don't paste it in shared chats.** Send only to yourself.
- **Don't leave it in your clipboard on a shared computer.**
- **Don't post it in a screenshot.**
- If you suspect a URL was exposed, end the session (`/exit` on desktop) and generate a new one.

## Compatibility

- Requires Claude Code 2.1.80 or later on the desktop side.
- Requires the Claude mobile app on the phone side.
- Works identically on macOS, Linux, and Windows hosts.

## See Also

- [06-telegram-bot.md](./06-telegram-bot.md) — outbound notifications + Telegram channel plugin
- [examples/telegram-channel-autolaunch/](../examples/telegram-channel-autolaunch/) — launchd + tmux pattern for the channel plugin
