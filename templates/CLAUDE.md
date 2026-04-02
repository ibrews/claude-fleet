# Knowledge Base — AI Navigation Guide

This is the navigation guide for your fleet's shared knowledge base. Every AI agent reads this file first to understand how to find, use, and update context.

## How This System Works

This folder is a shared git repo that all your machines read from and write to. It's the single source of truth for your fleet — inboxes, logs, decisions, and anything else that needs to persist across sessions and machines.

**Important:** Always access this repo via `~/knowledge/`. Never navigate into `~/.claude/` to reach it — that triggers permission prompts. If a symlink exists at `~/.claude/knowledge`, it's for tool compatibility only.

## Folder Structure

```
knowledge/
├── CLAUDE.md              ← You are here. Navigation + rules.
├── inbox/                 ← Inter-machine messaging (one file per machine)
│   ├── alpha.md
│   ├── beta.md
│   └── gamma.md
├── daily/                 ← Session logs (YYYY-MM-DD-machine.md)
├── fleet/                 ← Machine inventory and routing
│   └── roster.md
├── decisions/             ← Decision logs with rationale
├── projects/              ← Per-project context and notes
└── docs/                  ← Shared reference docs, runbooks, guides
```

Customize this structure for your needs. The important thing is that every folder has a clear purpose and agents know where to look.

## Knowledge Routing

| If the task involves...              | Look in...               |
|--------------------------------------|--------------------------|
| Messages for this machine            | `inbox/<machine>.md`     |
| What happened recently               | `daily/` (newest first)  |
| Machine roles and capabilities       | `fleet/roster.md`        |
| Why a past decision was made         | `decisions/`             |
| Active project context               | `projects/<name>/`       |
| How-to guides or reference           | `docs/`                  |

## Writing Rules

### General
- Use markdown. One topic per file.
- Prefer creating a new file over appending to a catch-all.
- Date format: `YYYY-MM-DD` everywhere.
- Include frontmatter on every file:

```yaml
---
title: "Short descriptive title"
updated: 2024-01-15
tags: [relevant, tags]
---
```

### Daily Logs

Each machine writes its own daily file to prevent merge conflicts:

**Filename:** `daily/YYYY-MM-DD-<machine>.md`

```markdown
---
title: "Daily Log — 2024-01-15 (alpha)"
updated: 2024-01-15
machine: alpha
tags: [daily]
---

# Daily Log — 2024-01-15 (alpha)

## What Was Done
- Completed X
- Fixed Y

## Decisions Made
- Chose A over B because...

## What's Next
- Task Z is queued

## Notes
- Anything worth remembering
```

To see everything across all machines on a given day:
```bash
ls ~/knowledge/daily/2024-01-15-*.md
```

### Decision Logs

When a non-trivial decision is made (architecture, tool choice, process change), save it:

```markdown
---
title: "Decision: Use SQLite over Postgres"
updated: 2024-01-15
tags: [decision, infrastructure]
---

# Decision: Use SQLite over Postgres

## Context
What prompted this decision.

## Options Considered
1. **SQLite** — pros, cons
2. **Postgres** — pros, cons

## Decision
SQLite. Reason: ...

## Consequences
What this means going forward.
```

## Sync Protocol

### Before writing
```bash
cd ~/knowledge && git pull --rebase origin master
```

### After writing
```bash
cd ~/knowledge && git add -A && git commit -m "type: short description" && git push origin master
```

### Conflict resolution
Multiple machines push concurrently. The hooks use `git pull --rebase` to minimize merge commits. For markdown files, conflicts usually auto-resolve. If a rebase fails, `git rebase --skip` — git history preserves everything.

### Machine-specific headings
When multiple machines append to the same file, use machine-specific headings (e.g., `### Session — alpha`) rather than interleaving. This prevents same-line conflicts.

## Rules for AI Agents

1. **Read before you write.** Check if context already exists before creating new files.
2. **Write back what you learn.** New decisions, completed work, session summaries — persist them.
3. **Don't duplicate — link.** Reference existing files rather than restating their content.
4. **Pull before writing, push after.** Minimize conflicts.
5. **Never force-push.** Always rebase.
6. **Stay out of `~/.claude/`.** Access this repo via `~/knowledge/` only.
7. **Daily logs are expected.** At the end of any meaningful session, write a daily log.
8. **Keep inbox items actionable.** One task per line, specific verbs, clear details.
