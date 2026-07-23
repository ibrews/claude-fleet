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

## Model Routing

**Default: cheapest model that does the job correctly.**

| Tier | Provider | When |
|------|----------|------|
| **Local** | Ollama (`localhost:11434`) | Free tasks — summarization, formatting, simple search |
| **Mid-tier** | Gemini 2.5 Flash (`$GEMINI_API_KEY`) | Research, drafts, large-file analysis; NVIDIA NIM (`$NVIDIA_API_KEY`) for code gen |
| **Claude** | Anthropic (`$ANTHROPIC_API_KEY`) | Orchestration, judgment, novel architecture, final review |

Within Claude itself: **Haiku 4.5** for mechanical edits → **Sonnet 4.6** for implementation (default, ~80% of tasks) → **Opus 4.8** for novel architecture or subtle root causes.

**Suggest downgrades in-session.** When the current Claude tier is overqualified, say so in one line and continue: *"This is a Sonnet task — consider `/model sonnet` to save Opus budget."* The user switches with `/model`; Claude cannot self-downgrade.

Confidence threshold for delegation: 90%+ = auto-dispatch; 70–89% = ask first; below 70% = Claude handles.

See `docs/13-model-routing.md` for full examples and curl commands.

## Concurrent Session Coordination

When multiple machines or sessions might work in parallel:

- **Session board:** Machines announce themselves via `session-board.sh heartbeat <slug> -S <status> -w "<doing>"` so others know what's running. Run `session-board.sh board` to see who's active. Entries stale after 15 minutes of no heartbeat.
- **Inbox claim:** Before starting an inbox item, claim it: `inbox-claim.sh triggers/<slug>.md`. This stamps `in_progress` + your PID so sibling sessions skip it. Release with `inbox-claim.sh triggers/<slug>.md done`. If a task is waiting on a human instead of abandoned, use `status: blocked` + `blocked_on:` — the inbox hook suppresses `blocked` items instead of nagging them as abandoned claims.
- **Git isolation:** Two sessions on the same repo → each gets its own branch via `git worktree add ../<slug> -b <branch>`. Never two sessions committing to one branch.

See `docs/14-concurrent-sessions.md` for full details.

## Behavior Rules

- **American spelling.** Always: `color` not `colour`, `center` not `centre`, `initialize` not `initialise`, `behavior` not `behaviour`. In code, comments, docs, UI strings, and commits.
- **Conventional commits.** Format: `type(scope): description`. Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`. One logical change per commit. Example: `feat(inbox): add claim protocol`.
- **Full git lifecycle.** Commit → push → merge finished branches back to `main` → delete the merged branch. Don't park completed work on side branches. Commit implies push.
- **README is the source of truth.** After any feature change, update the README in the same commit. If code and README disagree, the README is wrong — fix it.
- **Comments explain WHY.** Don't comment what the code does — well-named identifiers do that. Comment the non-obvious: hidden constraints, subtle invariants, workarounds for specific bugs.
