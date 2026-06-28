---
title: "Coordinating Concurrent Sessions"
updated: 2026-06-28
tags: [fleet, coordination]
---

# Coordinating Concurrent Sessions

When scaling a fleet of Claude Code agents across multiple physical machines or virtual environments, team orchestration is paramount. Without clear coordination protocols, concurrent sessions will step on each other—re-processing the same inbox items, introducing conflicting writes, and duplicating costly engineering efforts.

---

## The Problem: Colliding Agents

If multiple machines or independent terminal windows run agent sessions simultaneously on a shared task pool or repository, they inevitably collide. Typical issues include:
*   **Inbox Race Conditions:** Multiple agents pick up the same unassigned issue from the inbox queue.
*   **Conflicting Writes:** Agents modify identical files or directories simultaneously, resulting in messy merge conflicts.
*   **Duplicated Work:** Redundant token spend and run times executing identical diagnostics or builds.

---

## The Session Board Pattern

The **session board** acts as a lightweight, decentralized directory of all active sessions, stored directly inside the shared Knowledge Base (KB). Agents update this directory using a shared script (`session-board.sh`) that manages local heartbeats.

### Available Commands
*   `session-board.sh board`: Displays a table of all active machines, session slugs, statuses, current operations, and last heartbeats.
*   `session-board.sh heartbeat <slug> -S <status> -w <what>`: Sends a heartbeat updating status, current activity, and expected duration.
*   `session-board.sh checkout`: Deregisters the current session from the board upon completion or exit.

### Heartbeat Example
To signal an active execution phase:
```bash
session-board.sh heartbeat build-refactor -S building -w 'compiling main target' -e '10 min'
```

The board displays: machine name, session slug, status, what it's doing, and last heartbeat time. If a session fails to heartbeat for **more than 15 minutes**, the board automatically flags the entry as stale, signaling to other agents that the machine or process has stalled.

---

## The Inbox Claim Protocol

To prevent two agents from processing the same inbox item, the fleet enforces a strict **Inbox Claim Protocol**. 

Before analyzing or acting on an inbox task, an agent must execute:
```bash
inbox-claim.sh triggers/task-slug.md
```

This command modifies the corresponding task's trigger file, stamping:
1.  `status: in_progress`
2.  The calling agent's process ID (PID) and machine name as `claimed_by`
3.  The exact timestamp as `claimed_at`

Other sessions scanning the inbox detect this claim and automatically skip the item. 

### Liveness Checking
If an agent crashes or the terminal is closed before releasing the claim, other sessions check the claim's PID liveness. If the process is dead, the item auto-surfaces in reports as **claim abandoned**, allowing other agents to safely reclaim it.

### Releasing the Claim
When the task is complete, the agent releases the claim and marks the task as resolved:
```bash
inbox-claim.sh triggers/task-slug.md done
```

---

## Trigger Files

Actionable tasks require a corresponding tracking file stored under `triggers/<slug>.md`.

### Trigger Template

```yaml
---
title: "Optimize Image Compression Utility"
status: pending
claimed_by: ""
claimed_at: ""
completed_at: ""
---

# Context & Acceptance Criteria
- Optimize the bulk resizing script under scripts/compress.py.
- Target an execution speedup of at least 30%.
```

A task is officially **Done** only when:
1.  The trigger file status is changed to `completed` and `completed_at` is stamped.
2.  The corresponding inbox line is struck or marked as resolved.
3.  Both modifications are committed and pushed in a single, atomic git commit.

---

## Practical Git Isolation: Worktrees

When running multiple concurrent sessions on a single machine or repository, do not share a single working directory. This causes file locks and dirty state contamination.

Instead, leverage **Git Worktrees** to isolate each session's environment:
```bash
git worktree add ../slug -b branch-name
```
This spawns a completely isolated physical directory linked to a dedicated branch, letting multiple agents compile, test, and run builds in parallel without interference.
