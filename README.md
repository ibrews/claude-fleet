# Claude Fleet

Coordinate a fleet of computers each running [Claude Code](https://docs.anthropic.com/en/docs/claude-code), communicating asynchronously through git, with Telegram notifications for human-in-the-loop control.

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  alpha   │     │   beta   │     │  gamma   │
│ (macOS)  │     │(Windows) │     │ (Linux)  │
│Claude Code│     │Claude Code│     │Claude Code│
└────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                │
     └───── Tailscale VPN Mesh ────────┘
                      │
              ┌───────┴───────┐
              │  Shared Git   │
              │  Knowledge    │
              │  Base Repo    │
              │               │
              │  inbox/       │
              │  ├─ alpha.md  │
              │  ├─ beta.md   │
              │  └─ gamma.md  │
              └───────┬───────┘
                      │
              ┌───────┴───────┐
              │   Telegram    │
              │   Bot         │
              │               │
              │  ✅ ❌ ⚠️ 🔔   │
              │  Notifications│
              └───────────────┘
                      │
                   📱 You
```

## Important: Stay Out of `~/.claude/`

The `~/.claude/` directory is Claude Code's internal config directory. Accessing it directly triggers permission prompts and can interfere with Claude's operation.

**Rules:**
- Clone the knowledge base to **`~/knowledge`**, not `~/.claude/knowledge`
- Install fleet scripts to **`~/claude-fleet/`**, not `~/.claude/`
- The only file that *must* live in `~/.claude/` is **`settings.json`** (Claude Code requires it there)
- If you need a symlink for compatibility, create `~/.claude/knowledge → ~/knowledge` — but never access the KB through the symlink

## What This Does

- **Each machine runs Claude Code independently.** Your laptop, your desktop, your servers — each one can work autonomously.
- **Machines communicate through a shared git repo.** Each machine has an inbox file. Write a task to `inbox/beta.md`, push, and beta picks it up on its next session.
- **You get Telegram notifications.** When any machine finishes a task, you get a message with a status icon: ✅ success, ❌ error, ⚠️ hit turn limit, 🔔 needs your decision.
- **One command triggers all machines.** Run `fleet-inbox-check.sh` and every machine in your fleet checks its inbox in parallel.

## What This Is NOT

- Not a CI/CD system. There's no pipeline — machines work autonomously.
- Not a cloud orchestration tool. These are your physical machines, connected peer-to-peer.
- Not dependent on a central server. The git repo is the only shared resource.

## Prerequisites

- [Tailscale](https://tailscale.com/) (free tier works) — for SSH between machines
- A private git repo (GitHub, GitLab, etc.) — the shared knowledge base
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — installed on each machine
- [Node.js](https://nodejs.org/) — for the Telegram notification script
- A Telegram bot token (optional, for notifications) — [setup guide](telegram/setup-bot.md)

## Quick Start

### 1. Set up the network

Install [Tailscale](https://tailscale.com/download) on every machine and join them to the same tailnet. Verify with:

```bash
# From any machine
ssh <other-machine-name>
```

See [docs/02-tailscale-setup.md](docs/02-tailscale-setup.md) for details.

### 2. Create the shared knowledge base

Create a private git repo and clone it to `~/knowledge` on every machine:

```bash
# On each machine
git clone git@github.com:you/fleet-kb.git ~/knowledge
```

Create inbox files:

```bash
cd ~/knowledge
mkdir inbox
cp /path/to/claude-fleet/templates/inbox/example-machine.md inbox/alpha.md
cp /path/to/claude-fleet/templates/inbox/example-machine.md inbox/beta.md
git add inbox/ && git commit -m "init: inbox files" && git push
```

Optionally, create a compatibility symlink (some tools expect `~/.claude/knowledge`):
```bash
ln -s ~/knowledge ~/.claude/knowledge
```

See [docs/04-knowledge-repo.md](docs/04-knowledge-repo.md) for the full setup, including KB structure, CLAUDE.md navigation guide, and formatting rules.

### 3. Install Claude Code on every machine

```bash
# macOS / Linux
npm install -g @anthropic-ai/claude-code

# Verify
claude --version

# Authenticate
claude
# Then type: /login
```

See [docs/03-claude-code-install.md](docs/03-claude-code-install.md) for platform-specific notes.

### 4. Install the hooks

Copy the scripts to `~/claude-fleet/` on each machine:

```bash
mkdir -p ~/claude-fleet
cp scripts/kb-inbox-check.sh ~/claude-fleet/
cp scripts/kb-session-end.sh ~/claude-fleet/
cp scripts/notify-human.js ~/claude-fleet/
chmod +x ~/claude-fleet/kb-inbox-check.sh ~/claude-fleet/kb-session-end.sh
```

Add to `~/.claude/settings.json` (the one file that must live in `~/.claude/`):

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "$HOME/claude-fleet/kb-inbox-check.sh", "timeout": 30 }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "$HOME/claude-fleet/kb-session-end.sh", "timeout": 30 }] },
      { "hooks": [{ "type": "command", "command": "node $HOME/claude-fleet/notify-human.js", "timeout": 10 }] }
    ]
  }
}
```

See [templates/settings.json](templates/settings.json) for the full structure including permissions.

### 5. Configure the fleet trigger

Edit `scripts/fleet-inbox-check.sh` — add your machines to `ALL_MACHINES` and update `get_claude_cmd()` with the correct paths.

### 6. Test it

```bash
# Send a test message to one of your machines
cd ~/knowledge
echo '- [ ] [2024-01-01 12:00] @alpha → check: Are you alive? Reply to my inbox.' >> inbox/beta.md
git add inbox/ && git commit -m "test: ping beta" && git push

# Trigger beta to check its inbox
./scripts/fleet-inbox-check.sh beta
```

## Documentation

| Guide | Description |
|-------|-------------|
| [Fleet Overview](docs/01-fleet-overview.md) | Architecture and concepts |
| [Tailscale Setup](docs/02-tailscale-setup.md) | Connecting your machines |
| [Claude Code Install](docs/03-claude-code-install.md) | Per-platform installation |
| [Knowledge Repo](docs/04-knowledge-repo.md) | Setting up the shared git repo |
| [Inbox System](docs/05-inbox-system.md) | The messaging protocol |
| [Telegram Bot](docs/06-telegram-bot.md) | Notifications and remote control |
| [Hooks](docs/07-hooks.md) | Claude Code hook configuration |
| [Fleet Trigger](docs/08-fleet-trigger.md) | Triggering all machines at once |
| [Troubleshooting](docs/09-troubleshooting.md) | Common issues and fixes |

## Examples

- [Two-Machine Fleet](examples/two-machine-fleet/) — Minimal laptop + desktop setup
- [Five-Machine Fleet](examples/five-machine-fleet/) — Multi-role fleet with specialization

## How It Works Under the Hood

The magic is in three hooks:

1. **SessionStart** (`kb-inbox-check.sh`): When Claude starts, it pulls the knowledge base and checks for pending inbox items. If found, it injects them into Claude's context as high-priority instructions, so Claude processes them before doing anything else.

2. **Stop** (`kb-session-end.sh`): When Claude finishes, it auto-commits and pushes any changes to the knowledge base. No work is lost.

3. **Stop** (`notify-human.js`): After finishing, it sends a Telegram notification with a status icon so you know what happened without checking the terminal.

The fleet trigger script (`fleet-inbox-check.sh`) SSHes into every machine in parallel and runs `claude -p "check your inbox"` — which triggers the SessionStart hook, which processes the inbox.

## License

MIT
