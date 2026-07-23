
# Building a Well-Routable Second Brain

This is the single most important design principle that makes a Claude fleet work: a shared git repository that any Claude Code session on any machine can navigate from a cold start—without being told where things are. 

The key insight is that **AI agents navigate by routing tables, not by browsing**. If an agent must search aimlessly to find a standard operating procedure, the knowledge base is failing. It must route itself.

---

## 1. The Core Philosophy: "A Second Brain that Routes Itself"

When building a knowledge base (KB) for automated agents, you must avoid two primary failure modes:
1.  **The Flat Abyss (Too Flat):** Putting everything in a single, massive file or a flat root directory. This causes context window bloat, slows down grep searches, and generates duplicate content because agents cannot easily partition information.
2.  **The Labyrinth (Too Deep):** Burying files inside nested hierarchies. Agents are terrible at guessing arbitrary paths (e.g., `archive/2024/internal/dev/setup-notes/mac/`). If a path is deep, an agent will fail to find it without expensive, repetitive listing commands.

**The Right Abstraction:** Organize your KB into clear, semantic folders paired with a high-level navigation guide that contains explicit routing tables. Any new session, regardless of the machine or prompt, must be able to discover exactly where to look based on `CLAUDE.md` alone—without grep trial-and-error.

---

## 2. Recommended Folder Structure

Every fleet KB should standardize on these core directories:

*   `inbox/` — Inter-machine messaging and queue files (one file per machine, e.g., `inbox/alex-mbp.md`).
*   `daily/` — Per-machine chronological session logs, formatted as `YYYY-MM-DD-machine.md`.
*   `intelligence/techniques/` — Reusable engineering patterns, tool workarounds, and framework gotchas. This becomes the most valuable directory over time.
*   `intelligence/decisions/` — Architecture Decision Records (ADRs), prefixed by date (e.g., `YYYY-MM-DD-auth-migration.md`).
*   `fleet/` — Routing tables and machine inventory (specifically `roster.md` and `dispatch.md`).
*   `projects/<slug>/` — Isolated workspaces for active initiatives (e.g., `projects/billing-portal/`). **Rule:** Never put flat files directly in the `projects/` root.
*   `resources/templates/` — Reusable Markdown templates for decisions, techniques, and daily logs.
*   `triggers/` — Trigger files representing actionable inbox items with an explicit claim status (e.g., `claimed`, `pending`).

---

## 3. CLAUDE.md as a Routing Guide

The `CLAUDE.md` file in your repository root is the entry point for every agent session. Agents are programmed to read this first. It should act as a map, not a prose essay. Keep it under 100 lines and use compact routing tables. Update it immediately when you introduce a new major directory or initiative.

### Sample CLAUDE.md Skeleton

```markdown
# Fleet Knowledge Base Routing Guide

This repository is a self-routing knowledge base for the Claude fleet.

## Quick Actions (I Need To...)

| I need to... | Do this first |
| :--- | :--- |
| Find active projects | Read `projects/README.md` |
| View active machines | Read `fleet/roster.md` |
| Route a message to a machine | Append to `inbox/<machine-name>.md` |
| Record an architecture change | Create a file in `intelligence/decisions/` |
| Log a tool or API workaround | Write a guide in `intelligence/techniques/` |
| Check for pending actions | Scan `triggers/` |

## Domain Mapping (Task Involves...)

| Task involves... | Look in... |
| :--- | :--- |
| Local developer setup or runbooks | `resources/templates/` |
| System integrations or fleet topology | `fleet/dispatch.md` |
| Historical architectural choices | `intelligence/decisions/` |
| Specific active feature contexts | `projects/<slug>/` |
| Debugging known build/linter errors | `intelligence/techniques/` |
```

---

## 4. The Two File Types

To prevent your second brain from becoming a chaotic swamp, classify every file into one of two strict types:

1.  **Living Documents (No Date Prefix):** These are evolving standards, protocols, active routing tables, and runbooks (e.g., `fleet/roster.md`, `projects/billing-portal/architecture.md`). You update these in place, maintaining a single source of truth.
2.  **Point-in-Time Records (YYYY-MM-DD-topic.md):** These are records of historical events, meetings, specific decisions, or daily work logs (e.g., `intelligence/decisions/2026-06-28-database-migration.md`). **Rule:** Never rewrite or alter the conclusions of these files; only append annotations or mark them as deprecated with a pointer to a newer living document.

---

## 5. Frontmatter Standards

Every Markdown file in the KB (except `CLAUDE.md`) must include a minimal YAML frontmatter block. This drives structural grep-ability and automatic categorization in visual viewers.

```yaml
---
title: "Database Indexing Guidelines"
updated: 2026-06-28
tags: [database, performance, standard]
---
```

*   `title`: A clear, search-friendly title.
*   `updated`: ISO date (`YYYY-MM-DD`) tracking the last modification.
*   `tags`: Standardized, lower-case categories for indexing.

---

## 6. The "Techniques Inline" Rule

The most valuable asset in an engineering KB is the hard-won knowledge of bugs, gotchas, and quirky workarounds. 

**The Rule:** The moment you resolve a build failure, discover an API quirk, or find a tool workaround, write it to `intelligence/techniques/` **during that exact same turn**. Do not wait or tell yourself "I'll write it up later." 

Name the file precisely after the problem, not a generic subject. Use the format `what-went-wrong-and-why.md`.

### Sample Techniques Template (`resources/templates/technique.md`)

```markdown
---
title: "Gotcha: [Precise error message or behavior]"
updated: YYYY-MM-DD
tags: [service/tool, workaround, error-code]
---

# Gotcha: [Precise description of the failure]

## Context
Describe what was being attempted and on which environment/platform.

## The Failure
Paste the exact error message, stack trace, or buggy behavior.

## The Fix
Explain the exact step-by-step resolution. 

```bash
# Code block showing the fix
```

## Why This Happens
Explain the underlying cause (e.g., "The CLI tool defaults to interactive mode unless the quiet flag is passed").
```

---

## 7. Retrieval Miss Tracking

When an agent executes three or more separate `grep_search` or `glob` patterns without finding a known piece of information, this is a **retrieval miss**. 

Document these failures in `fleet/kb-retrieval-misses.md`. 
*   **Log:** What was the agent looking for? Which search patterns failed?
*   **Resolution:** Where was the document actually located, and how did you update `CLAUDE.md` or rename the file to make it easily discoverable in the future?

---

## 8. Key Writing Rules

*   **Pull and Push Instantly:** Always pull changes before writing to the KB, and commit and push immediately after writing. Never let knowledge linger unstaged or uncommitted.
*   **One Topic Per File:** Do not append unrelated notes to existing catch-all files. Keep files highly cohesive.
*   **The Routing Question:** Before writing, ask yourself: *"Would another machine or a fresh agent session benefit from knowing this?"* If yes, put it in the KB. If it is purely machine-specific (e.g., a local shell path or personal preferences), keep it in the machine's local auto-memory.

---

## 9. What NOT to Put in the KB

Keep your shared KB secure and lean by strictly excluding:
*   **Secrets:** API keys, passwords, database credentials, and dollar amounts.
*   **Ephemeral State:** "Currently working on step 2 of task X." That belongs on your active session/dispatch board, not in permanent documentation.
*   **Redundant Git Metadata:** Explanations of who changed what or complex file histories. Git log is the source of truth for history.
*   **Raw Output Bloat:** Do not paste massive command stdout or logs. Distill the lesson down to the core evidence and the fix.

## Memory: per-machine daily digests, and a graveyard

Two practices that keep a long-lived shared brain honest:

**Daily digests with hygiene rules.** `daily/YYYY-MM-DD-<machine>.md` is one digest per machine per
day, upserted at *checkpoints* — right after "works now / fixed / decided / hit a gotcha" — never
batched to session end (sessions die; buffered notes die with them). Hygiene rules: record only
what was non-obvious — corrections, confirmed approaches, failure modes and their fixes — and never
restate what git history already records. This is how agents survive session death without their
context.

Daily logs are **append-only**. When later knowledge disproves an old entry, don't rewrite history —
add an inline marker directly under the stale line so no old log can silently lie to a future reader:

```
> ⚠️ SUPERSEDED YYYY-MM-DD: <one line: what's now known> — see <canonical path>.
```

**An explicit graveyard.** Stale context in an agent fleet propagates confidently, and a KB that
only ever adds has no way to say "this is dead." When a doc is superseded *wholesale* (not just one
line), `git mv` it into an `_archive/` folder next to where it lived and prepend a tombstone:

```
> ☠️ ARCHIVED YYYY-MM-DD: <why> — superseded by <path, or "nothing (dead end)">.
```

The rule that makes the graveyard work: **anything under `_archive/` must never be treated as
current truth.** Agents read it for history only; if archived content contradicts a live doc, the
live doc wins with no judgment call. Never archive daily logs (append-only + SUPERSEDED markers) or
decision records (point-in-time by design) — archive the living docs that stopped being true.
