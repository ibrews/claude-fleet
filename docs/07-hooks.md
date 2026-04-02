# Claude Code Hooks

Hooks are the mechanism that makes the fleet work autonomously. Claude Code supports hooks that run shell commands at specific lifecycle points.

## Path Convention

Fleet scripts live in `~/claude-fleet/`. The only file that belongs in `~/.claude/` is `settings.json` (Claude Code requires it there). Never put scripts, env files, or the KB inside `~/.claude/` — it causes unnecessary permission prompts.

## Hook Types Used

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

## Windows Notes

On Windows, `bash` in the hook command may resolve to WSL's bash (which has a different filesystem). Two solutions:

1. **Use `node` instead of `bash`** for hooks. The `notify-human.js` script is designed for this.
2. **Use Git Bash explicitly**: `"command": "C:/Program Files/Git/bin/bash.exe $USERPROFILE/claude-fleet/kb-inbox-check.sh"`

For the `$HOME` or `$USERPROFILE` variable in hook commands, Claude Code expands these before execution on all platforms.

## Full settings.json

See [templates/settings.json](../templates/settings.json) for a complete configuration with all hooks.
