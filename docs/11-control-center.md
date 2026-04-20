# Fleet Control Center

> **Note:** The Control Center source code (`server.js`, `public/index.html`) is **not included** in this repo. It is a separate Node.js application that you create or obtain independently. This document describes the architecture, API, and setup so you can build or configure your own instance. You will need to create `server.js` (Express + SQLite REST API) and `public/index.html` (single-page dashboard) yourself, or use the reference implementation if one is provided to you separately.

A centralized web dashboard for fleet management — machine status, inbox overview, task dispatch, and development tracking.

> **Scope note:** The Control Center is a desktop/web visibility + dispatch layer, not a phone-access tool. If you want to drive a live Claude Code session from your phone, use the built-in `/remote-control` command ([12-remote-control.md](./12-remote-control.md)). For outbound Telegram pings, see [06-telegram-bot.md](./06-telegram-bot.md).

## Overview

While the inbox system (docs 05) handles async messaging via git, the Control Center adds a **real-time web dashboard** for fleet-wide visibility and instant task dispatch.

| Feature | Inbox System | Control Center |
|---------|-------------|----------------|
| Communication | Async (git commit/push) | Real-time (REST API) |
| Task dispatch | Write to inbox, picked up on next session | SSH + headless Claude, instant results |
| Visibility | Read markdown files | Web dashboard with live status |
| Hosting | Distributed (every machine has a copy) | Centralized (runs on one always-on machine) |

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Fleet Control Center (Node.js + SQLite)          │
│  Running on gateway machine (e.g., Sam)           │
│                                                    │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │ Machine  │  │  Inbox   │  │  Task Dispatch   │ │
│  │ Registry │  │ Manager  │  │  (SSH + Claude)  │ │
│  └─────────┘  └──────────┘  └──────────────────┘ │
│       │             │               │              │
│       │        ┌────┴────┐    ┌─────┴─────┐       │
│       │        │ KB Git  │    │ Tailscale │       │
│       │        │ Inbox   │    │ SSH Mesh  │       │
│       │        │ Files   │    └───────────┘       │
│  ┌────┴────┐   └─────────┘                        │
│  │ SQLite  │                                       │
│  │   DB    │   ┌──────────────────────────────┐   │
│  └─────────┘   │  Single-Page Dashboard (HTML) │   │
│                └──────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

## Setup

### Prerequisites
- Node.js 18+
- A knowledge base with inbox files (see docs 04-05)
- Tailscale mesh network (see docs 02)
- SSH access between machines (key-based auth)

### Installation

```bash
# On your always-on gateway machine
mkdir ~/fleet-control-center
cd ~/fleet-control-center

# Copy or create server.js, public/index.html, package.json
npm install  # express, better-sqlite3, multer, cors

# Start
node server.js
# Runs on port 3333 by default (set PORT env to change)
```

### Keep it running (macOS LaunchAgent)

```bash
cat > ~/Library/LaunchAgents/com.fleet.control-center.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.fleet.control-center</string>
  <key>ProgramArguments</key><array>
    <string>/opt/homebrew/bin/node</string>
    <string>/Users/YOU/fleet-control-center/server.js</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>/Users/YOU/fleet-control-center</string>
  <key>StandardOutPath</key><string>/tmp/fleet-control-center.log</string>
  <key>StandardErrorPath</key><string>/tmp/fleet-control-center.err</string>
</dict></plist>
EOF
launchctl load ~/Library/LaunchAgents/com.fleet.control-center.plist
```

### Register machines

```bash
curl -X POST http://localhost:3333/api/fleet/machines \
  -H "Content-Type: application/json" \
  -d '{"id":"my-machine","name":"My Machine","tailscale_ip":"100.x.y.z","os":"macOS","role":"Dev machine"}'
```

### Add heartbeats to hooks

Add to your SessionStart hook (e.g., `kb-inbox-check.sh`):
```bash
curl -s -X POST http://GATEWAY_IP:3333/api/fleet/machines/$(hostname)/heartbeat >/dev/null 2>&1 &
```

## Task Dispatch

Three dispatch modes:

### Inbox Mode
Writes a task to the target machine's inbox markdown file. The machine picks it up on its next Claude session start.

### Instant Mode
SSHs to the target machine and runs:
```bash
claude -p "your task here" --max-turns 15 --output-format json
```

The result appears in the Dispatch Log within seconds to minutes.

### What instant dispatch can do

Headless Claude runs as a CLI process via SSH. It has **full filesystem and shell access** but **no GUI access**.

**Works well:**
- File operations: read, write, search, organize files
- Git operations: pull, push, status, log, diff
- System info: disk space, processes, installed software
- Code tasks: run tests, lint, build, deploy
- Data queries: search files, count lines, parse logs
- KB updates: write status reports, update inbox

**Won't work:**
- Opening GUI applications (Unreal Editor, Notepad, browsers)
- Interactive tasks requiring user input
- Tasks longer than 5 minutes (SSH timeout)
- Anything requiring desktop session access

### Smart Dispatch (Auto-Route)

Select "🧠 Auto" in the machine dropdown and the Control Center will:

1. **Classify** the task by matching keywords against routing rules (e.g., "benchmark GPU" → `gpu-compute`)
2. **Check health** of the primary machine (SSH ping or local detection if running on the same host)
3. **Fall back** to the next machine in the chain if the primary is offline
4. **Execute** via instant SSH or local spawn

The classification preview shows in real-time as you type: `→ fort (gpu-compute)`.

#### Routing rules

Rules are ordered from most specific to most general. Task classification stops at the first match:

| Task Type | Keywords | Primary | Fallbacks |
|-----------|----------|---------|-----------|
| game-engine | unreal, ue5, blueprint, lighting | GPU machine | Secondary GPU |
| gpu-compute | gpu, cuda, train, inference, pytorch | GPU machine | Other GPU machines |
| apple-dev | xcode, ios, swift, testflight | Mac with Xcode | Other Mac |
| eval | eval, benchmark, score | Always-on gateway | Bulk processor |
| ops | deploy, docker, restart, service | Always-on gateway | Dev machine |
| design | design, svg, mockup, figma | GPU (design model) | Bulk processor |
| refactoring | refactor, review, lint, optimize | Bulk processor | GPU, dev |
| reasoning | architecture, strategy, tradeoff | GPU (reasoning model) | Bulk processor |
| bulk-processing | document, analyze, summarize, batch | High-VRAM machine | Gateway |
| quick-check | status, check, disk, uptime, health | Always-on gateway | Dev, lightweight |
| coding | code, html, implement, build, create | Best code model | Secondary code |

#### Eval-driven routing

If you run model evaluations across your fleet, the routing rules can be automatically updated from eval data. The `update-routing.js` script reads your eval results and regenerates the `TASK_ROUTING` array based on actual model performance scores:

```bash
# Preview what routing would look like based on eval data:
node update-routing.js

# Apply to server.js automatically:
node update-routing.js --apply
```

This means your routing improves as you test more models — a model that scores 7.38 on coding tasks will be preferred over one that scores 5.10, regardless of which machine it's on.

### Model routing

The dispatch UI includes a model selector:
- **Auto**: Let Claude decide
- **Opus**: Complex reasoning, architecture, code review
- **Sonnet**: Balanced coding tasks
- **Haiku**: Quick lookups, simple edits, status checks

## API Reference

### Fleet Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/fleet/machines` | List machines with live status |
| `POST` | `/api/fleet/machines` | Register/update machine |
| `POST` | `/api/fleet/machines/:id/heartbeat` | Update last_seen |
| `GET` | `/api/fleet/machines/:id/inbox` | Read machine inbox |
| `DELETE` | `/api/fleet/machines/:id/inbox/:idx` | Delete pending item |
| `POST` | `/api/fleet/machines/:id/inbox/:idx/done` | Mark item done |
| `GET` | `/api/fleet/inbox` | All inboxes summary |
| `POST` | `/api/fleet/dispatch` | Dispatch task (manual target) |
| `POST` | `/api/fleet/dispatch/smart` | Smart dispatch (auto-classify + health check + fallback) |
| `GET` | `/api/fleet/classify` | Classify a task without dispatching |
| `GET` | `/api/fleet/dispatches` | Recent results + running tasks |
| `GET` | `/api/fleet/tasks/:id` | Poll for task result |
| `POST` | `/api/fleet/workflow` | Execute multi-step workflow chain |
| `GET` | `/api/fleet/workflow/:id` | Poll workflow status |
| `GET` | `/api/fleet/health` | Ping all machines via SSH |
| `GET` | `/api/fleet/activity` | Event timeline |
| `GET` | `/api/fleet/dashboard` | Fleet summary |

### Dispatch Request

```json
POST /api/fleet/dispatch
{
  "target": "beta",
  "message": "check disk space and report back",
  "sender": "control-center",
  "mode": "instant",
  "model": "haiku"
}
```

## Integration with existing fleet tools

The Control Center reads inbox files from the Knowledge Base (`~/knowledge/inbox/`). When it modifies an inbox item (mark done, delete, dispatch), it auto-commits and pushes to git.

Add a "Control Center" tab to an existing dashboard by embedding it in an iframe:

```html
<iframe src="http://GATEWAY_IP:3333" style="width:100%;height:100vh;border:none"></iframe>
```
