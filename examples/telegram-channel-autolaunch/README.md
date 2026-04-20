# Telegram Channel Auto-Launch (macOS / launchd + tmux)

A ready-to-adapt pattern for running the official Telegram channel plugin (`plugin:telegram@claude-plugins-official`) as a persistent, DM-driven Claude Code session that survives logout and reboots.

See [docs/06-telegram-bot.md](../../docs/06-telegram-bot.md#part-b--live-session-access) for the full explanation.

## Single-Poller Constraint — Read This First

The Telegram Bot API allows **exactly one** active `getUpdates` poller per bot token. That means:

- Only **one machine in your entire fleet** should run this for a given bot token.
- Pick the machine with the best uptime and the canonical checkout of whatever working directory you want the session to be in (e.g., your KB).
- Use a **different bot token** from the one your outbound notification hooks (`notify-human.js`) use — otherwise the channel session will swallow the updates the notification bot expects.

## Files

| File | What it does |
|------|--------------|
| `start-telegram-channel-session.sh` | Spawns the Claude session in a named tmux session. Kills stale sessions first. |
| `com.example.telegram-channel.plist` | launchd agent — runs the start script at login. |
| `uninstall-telegram-channel-autolaunch.sh` | Unloads the agent, kills the tmux session, removes the plist. |

## Placeholders To Replace

All three files contain `REPLACE_ME_*` placeholders. Before installing, grep and substitute:

| Placeholder | Replace with |
|-------------|--------------|
| `REPLACE_ME_USER` | Your macOS username (e.g., the output of `whoami`) |
| `REPLACE_ME_HOME` | Your home directory (e.g., `/Users/you`) |
| `REPLACE_ME_KB_DIR` | Absolute path to the working directory the session should `cd` into (commonly your KB repo) |
| `REPLACE_ME_LABEL` | A reverse-DNS launchd label, e.g. `com.yourname.telegram-channel`. Must match between the script's `AGENT_LABEL` and the plist's `Label` and filename. |

Quick substitution (macOS):

```bash
cd examples/telegram-channel-autolaunch
sed -i '' \
  -e "s|REPLACE_ME_USER|$(whoami)|g" \
  -e "s|REPLACE_ME_HOME|$HOME|g" \
  -e "s|REPLACE_ME_KB_DIR|$HOME/knowledge|g" \
  -e "s|REPLACE_ME_LABEL|com.yourname.telegram-channel|g" \
  start-telegram-channel-session.sh uninstall-telegram-channel-autolaunch.sh com.example.telegram-channel.plist
```

Then rename the plist to match its label:

```bash
mv com.example.telegram-channel.plist com.yourname.telegram-channel.plist
```

## Install

```bash
# 1. Put the scripts somewhere stable
mkdir -p ~/.claude/scripts
cp start-telegram-channel-session.sh ~/.claude/scripts/
cp uninstall-telegram-channel-autolaunch.sh ~/.claude/scripts/
chmod +x ~/.claude/scripts/*.sh

# 2. Install the launchd agent
cp com.yourname.telegram-channel.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.yourname.telegram-channel.plist
```

Check it's running:

```bash
tmux attach -t telegram-channel
# Ctrl-b d to detach without killing the session
```

## Uninstall

```bash
~/.claude/scripts/uninstall-telegram-channel-autolaunch.sh
```

## Prerequisites

- Claude Code installed (`which claude` should resolve)
- `tmux` installed (`brew install tmux`)
- Telegram channel plugin installed:
  ```bash
  claude plugin install plugin:telegram@claude-plugins-official
  ```
- Bot paired via `/telegram:configure` in an interactive session first (the channel plugin stores pairing state in `~/.claude/channels/telegram/`)

## Linux Note

launchd is macOS-only. On Linux, translate the plist into a `systemd --user` unit:

```ini
# ~/.config/systemd/user/telegram-channel.service
[Unit]
Description=Claude Code Telegram channel session

[Service]
Type=forking
ExecStart=%h/.claude/scripts/start-telegram-channel-session.sh
Restart=no

[Install]
WantedBy=default.target
```

Enable with `systemctl --user enable --now telegram-channel`.
