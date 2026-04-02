# Fleet Trigger

The fleet trigger script is how you tell all your machines to check their inboxes at once.

## How It Works

1. Pushes any local KB changes (so all machines get the latest)
2. SSHes into each machine in parallel
3. Runs `claude -p "<prompt>" --max-turns 15` on each
4. Waits for all to finish
5. Collects results and sends a Telegram summary

## Setup

Edit `scripts/fleet-inbox-check.sh`:

```bash
# Add your machine names (must match SSH config or Tailscale hostnames)
ALL_MACHINES="alpha beta gamma"

# Configure SSH hosts and Claude paths
get_host() {
  case "$1" in
    alpha) echo "localhost" ;;  # the machine running this script
    *)     echo "$1" ;;
  esac
}

get_claude_cmd() {
  case "$1" in
    alpha) echo "/opt/homebrew/bin/claude" ;;  # macOS
    beta)  echo "claude" ;;                     # Windows (in PATH)
    gamma) echo "/usr/local/bin/claude" ;;      # Linux
    *)     echo "claude" ;;
  esac
}
```

## Usage

```bash
# Trigger all machines
./scripts/fleet-inbox-check.sh

# Trigger specific machines
./scripts/fleet-inbox-check.sh alpha beta

# Run from cron (e.g., every hour)
0 * * * * /path/to/fleet-inbox-check.sh >> /tmp/fleet-trigger.log 2>&1
```

## Output

Terminal:
```
[prep] Syncing knowledge base...
[alpha] Triggering inbox check...
[beta] Triggering inbox check...
[gamma] Triggering inbox check...

Waiting for 3 machine(s)...

[alpha] DONE — see /tmp/inbox-check-alpha.log
[beta] DONE — see /tmp/inbox-check-beta.log
[gamma] FAILED — see /tmp/inbox-check-gamma.log

Completed: 2/3 succeeded
[telegram] Summary sent.
```

Telegram:
```
📬 Fleet Inbox Check — 14:30

✅ alpha — done
✅ beta — done
❌ gamma — failed

2/3 machines responded.
```

## Performance Notes

- **Windows machines are slower** to respond. Claude Code on Windows via SSH may buffer output until completion. Sessions can take 3-5 minutes even for simple tasks.
- **`--max-turns 15`** is a safety limit. If a machine hits it, the Telegram summary shows ⚠️. Increase if your tasks need more turns.
- **Logs are at `/tmp/inbox-check-<machine>.log`** for debugging individual machines.
