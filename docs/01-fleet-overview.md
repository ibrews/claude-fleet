# Fleet Overview

## Architecture

A Claude Fleet is a group of computers — your laptop, desktops, servers, whatever — each running Claude Code independently, connected through two layers:

### 1. The Network Layer (Tailscale)

[Tailscale](https://tailscale.com/) creates a peer-to-peer VPN mesh between all your machines. No port forwarding, no firewall rules. Every machine can SSH to every other machine by name.

### 2. The Communication Layer (Git)

A shared git repository acts as an asynchronous message bus. Each machine has an "inbox" file where other machines (or you) can leave tasks. Machines check their inbox at session start, process pending items, and push results back.

### 3. The Human Layer (Telegram)

A Telegram bot sends you notifications when machines finish tasks, hit errors, or need your input. You stay in the loop without watching terminals.

## File Layout on Each Machine

```
~/
├── knowledge/          ← Shared git KB repo (clone here, not in .claude!)
│   ├── CLAUDE.md       ← Navigation guide for AI agents
│   ├── inbox/          ← Inter-machine messaging
│   └── daily/          ← Session logs
├── claude-fleet/       ← Fleet scripts (hooks, notifications)
│   ├── kb-inbox-check.sh
│   ├── kb-session-end.sh
│   ├── notify-human.js
│   └── fleet.env       ← Telegram credentials
└── .claude/
    └── settings.json   ← Claude Code config (only file that must be here)
```

**Stay out of `~/.claude/`.** It's Claude Code's internal directory. Accessing it triggers permission prompts. The knowledge base goes in `~/knowledge/`, fleet scripts go in `~/claude-fleet/`, and only `settings.json` lives in `~/.claude/`.

## Message Flow

```
Machine A                    Git Repo                     Machine B
─────────                    ────────                     ─────────

1. Write task to
   inbox/machine-b.md    →  2. git push
                                                    ←  3. git pull
                                                       4. Claude reads inbox
                                                       5. Claude processes task
                                                       6. Marks done, writes
                                                          confirmation to
                                                          inbox/machine-a.md
                                                    →  7. git push
                             8. Available for
                                Machine A to pull

                                    ↓
                             9. Telegram notification
                                sent to human
                                    ↓
                                📱 You see:
                                ✅ machine-b — task complete
```

## What Each Hook Does

| Hook | Script | When | What |
|------|--------|------|------|
| SessionStart | `kb-inbox-check.sh` | Claude session begins | Pulls KB, checks inbox, injects pending items into Claude's context |
| Stop | `kb-session-end.sh` | Claude session ends | Auto-commits and pushes any KB changes |
| Stop | `notify-human.js` | Claude session ends | Sends Telegram notification with status icon |

## Key Design Decisions

- **Async over sync.** Machines don't need to be online simultaneously. Write to an inbox, push, and the target machine picks it up whenever it's next active.
- **Git as the source of truth.** Every message, every state change is in git history. Full auditability, easy rollback.
- **No central server.** The git repo (GitHub/GitLab) is the only shared infrastructure. If it's down, machines keep working locally.
- **Claude does the thinking.** The inbox contains human-readable tasks, not rigid API payloads. Claude interprets and executes them using its full capabilities.
- **Stay out of `.claude/`.** Fleet data lives in `~/knowledge/` and `~/claude-fleet/` to avoid permission issues. Only `settings.json` needs to be in `~/.claude/`.
