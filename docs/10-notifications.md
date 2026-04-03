# Mid-Session Notifications

The inbox system delivers messages on session start. But what if Machine A is mid-session and Machine B finishes a task it requested? Notifications solve this — they inject messages into an **active** Claude session within ~60 seconds.

## How It Works

```
Machine B finishes task
        │
        ▼
Writes ~/knowledge/notifications/alpha/20240101-task-done.json
        │
        ▼
   git push
        │
   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ (up to 60 seconds)
        │
        ▼
Machine A's cron pulls KB
Stages notification to /tmp/fleet-pending/
Removes from KB, pushes
        │
        ▼
Machine A's PostToolUse hook fires
Reads /tmp/fleet-pending/*.json
Injects into Claude's active context
        │
        ▼
Claude tells you: "📬 From beta: Build complete — v1.2.0 uploaded to TestFlight"
```

Three layers keep the hook fast:

1. **Sender** writes a JSON file to the KB and pushes
2. **Cron** (every 60s) on the receiver pulls, stages notifications locally, cleans up the KB
3. **PostToolUse hook** (every 10s) checks the local staging dir (~5ms) and injects if found

## Notification Format

```json
{
  "from": "beta",
  "to": "alpha",
  "subject": "Build complete",
  "message": "Built v1.2.0 and uploaded to TestFlight. Build #42.",
  "timestamp": "2024-01-15T14:30:00Z",
  "priority": "normal"
}
```

**Priority levels:**
- `normal` — delivered on next hook cycle
- `urgent` — same delivery, but displayed with a 🚨 icon

## Setup

### 1. Create the notification directories

In your knowledge base repo:

```bash
cd ~/knowledge
mkdir -p notifications/alpha notifications/beta notifications/gamma
# One directory per machine in your fleet
```

### 2. Install the PostToolUse hook

Copy the script:

```bash
cp scripts/check-notifications.sh ~/claude-fleet/
chmod +x ~/claude-fleet/check-notifications.sh
```

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "hooks": [{
          "type": "command",
          "command": "$HOME/claude-fleet/check-notifications.sh",
          "timeout": 5,
          "statusMessage": "Checking fleet notifications..."
        }]
      }
    ]
  }
}
```

### 3. Set up the notification sync cron

```bash
cp scripts/fleet-sync-notifications.sh ~/claude-fleet/
chmod +x ~/claude-fleet/fleet-sync-notifications.sh
```

Add to crontab (`crontab -e`):

```
* * * * * FLEET_MACHINE_NAME=alpha ~/claude-fleet/fleet-sync-notifications.sh >> /tmp/fleet-sync.log 2>&1
```

Replace `alpha` with your machine's fleet name.

**On Windows**, use Task Scheduler instead:

```powershell
schtasks /create /tn "FleetNotificationSync" /tr "node %USERPROFILE%\claude-fleet\fleet-sync-notifications.js" /sc minute /mo 1
```

### 4. Install the send helper

```bash
cp scripts/send-notification.js ~/claude-fleet/
```

Usage:

```bash
node ~/claude-fleet/send-notification.js alpha "Task complete" "Built the APK and uploaded it" normal
```

Or from a bash script:

```bash
# Bash:
~/claude-fleet/send-notification.sh alpha "Task complete" "Built the APK"
# Or Node.js (cross-platform):
node ~/claude-fleet/send-notification.js alpha "Task complete" "Built the APK"
```

## Sending Notifications from Hooks

The inbox processing hook (`kb-inbox-check.sh`) automatically instructs Claude to send notifications when completing tasks from other machines. When Claude processes an inbox item from Machine B and finishes it, it writes a notification to `notifications/beta/` and pushes — so Machine B knows the result mid-session.

## Design Decisions

- **No daemon required.** The cron + hook approach avoids persistent processes. If the cron stops, notifications just arrive later (on next manual KB pull).
- **No git on every tool call.** The hook only checks a local directory. Git operations are isolated in the cron.
- **Self-cleaning.** The sync script removes delivered notifications from the KB so they don't accumulate.
- **Idempotent.** If the cron runs twice before the hook fires, notifications just queue up locally.
- **Graceful degradation.** If the cron isn't set up, the inbox system still works — notifications just don't arrive mid-session.
