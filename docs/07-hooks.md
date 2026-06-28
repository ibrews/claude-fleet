# Claude Code Hooks

Hooks are the mechanism that makes the fleet work autonomously. Claude Code supports hooks that run shell commands at specific lifecycle points.

## Path Convention

Fleet scripts live in `~/claude-fleet/`. The only file that belongs in `~/.claude/` is `settings.json` (Claude Code requires it there). Never put scripts, env files, or the KB inside `~/.claude/` — it causes unnecessary permission prompts.

## Hook Types Used

### SessionStart — Session Board

Before checking the inbox, this hook registers the current session on the board and prints who else is active. This is how you know whether another session is already compiling something, using a device, or working in the same repo.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [{
          "type": "command",
          "command": "$HOME/claude-fleet/session-board-show.sh",
          "timeout": 15,
          "statusMessage": "Checking session board..."
        }]
      }
    ]
  }
}
```

The hook auto-registers your session with a slug derived from your working directory + session ID, then prints a table of all active sessions showing their status, what singleton resources they hold (build engine, device, etc.), and when they last heartbeated. Sessions older than 15 minutes are flagged as stale.

After your session ends, `session-board-checkout.sh` (wired to `SessionEnd`) removes your entry automatically.

### SessionStart — Inbox Check

When Claude starts a session, this hook pulls the knowledge base and checks for pending inbox items. If found, it injects them into Claude's context so they're processed before anything else.

**This is the most important hook.** It's what makes the inbox system work — Claude doesn't just read the inbox file, it gets the pending items injected as high-priority instructions.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [{
          "type": "command",
          "command": "$HOME/claude-fleet/kb-inbox-check.sh",
          "timeout": 30,
          "statusMessage": "Checking inbox..."
        }]
      }
    ]
  }
}
```

**How context injection works:**

The script outputs JSON with a special structure that Claude Code understands:

```json
{
  "systemMessage": "📬 3 pending inbox item(s) found",
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "IMPORTANT: Process these inbox items FIRST..."
  }
}
```

The `additionalContext` field gets added to Claude's context window, ensuring it sees and acts on the inbox items.

### Stop — Auto-Sync Knowledge Base

When Claude finishes, this hook commits and pushes any changes to the knowledge base:

```json
{
  "Stop": [
    {
      "hooks": [{
        "type": "command",
        "command": "$HOME/claude-fleet/kb-session-end.sh",
        "timeout": 30
      }]
    }
  ]
}
```

### Stop — Telegram Notification

Also on Stop, sends a notification to Telegram:

```json
{
  "Stop": [
    {
      "hooks": [{
        "type": "command",
        "command": "node $HOME/claude-fleet/notify-human.js",
        "timeout": 10
      }]
    }
  ]
}
```

Multiple Stop hooks run in sequence — the KB sync runs first, then the notification.

### SessionEnd — Session Board Checkout

Automatically removes your session entry from the board when the session ends. Paired with the SessionStart board hook.

```json
{
  "SessionEnd": [
    {
      "hooks": [{
        "type": "command",
        "command": "$HOME/claude-fleet/session-board-checkout.sh",
        "timeout": 10,
        "statusMessage": "Checking out of session board..."
      }]
    }
  ]
}
```

### PostToolUse — Mid-Session Notifications

After every tool call, this hook checks for notifications from other fleet machines:

```json
{
  "PostToolUse": [
    {
      "hooks": [{
        "type": "command",
        "command": "$HOME/claude-fleet/check-notifications.sh",
        "timeout": 5
      }]
    }
  ]
}
```

The hook only reads a local directory (~5ms), so it adds negligible overhead. A separate cron job handles the git pull. See [Notifications](10-notifications.md) for full setup.

## Headless Sessions (node path)

When running Claude headless (`claude -p "prompt" --max-turns N`), the shell profile doesn't load, so `node` may not be in PATH. Use the full path in hook commands:

- **macOS (Homebrew):** `/opt/homebrew/bin/node`
- **Linux:** `/usr/bin/node` or `/usr/local/bin/node`
- **Windows:** `C:\Program Files\nodejs\node.exe`

## Windows Notes

On Windows, `bash` in the hook command may resolve to WSL's bash (which has a different filesystem). Two solutions:

1. **Use `node` instead of `bash`** for hooks. The `notify-human.js` script is designed for this.
2. **Use Git Bash explicitly**: `"command": "C:/Program Files/Git/bin/bash.exe $USERPROFILE/claude-fleet/kb-inbox-check.sh"`

For the `$HOME` or `$USERPROFILE` variable in hook commands, Claude Code expands these before execution on all platforms.

## Machine Name Detection

Fleet scripts need to know your machine's name to find the right inbox file (e.g., `inbox/alpha.md`).

Detection order:
1. `FLEET_MACHINE_NAME` env var (highest priority)
2. `KB_MACHINE_NAME` env var (legacy/fallback)
3. System hostname

Set it explicitly in your crontab or hook environment to avoid hostname mismatches:

```bash
export FLEET_MACHINE_NAME=alpha
```

In a crontab entry:
```
* * * * * FLEET_MACHINE_NAME=alpha ~/claude-fleet/fleet-sync-notifications.sh >> /tmp/fleet-sync.log 2>&1
```

If your inbox isn't being processed, this is the first thing to check. Run `hostname` on the machine and compare it to the inbox filename in your KB. If they don't match, set `FLEET_MACHINE_NAME` explicitly.

## Full settings.json

See [templates/settings.json](../templates/settings.json) for a complete configuration with all hooks.
