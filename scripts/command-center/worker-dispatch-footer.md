# Worker-dispatch footer

Append this verbatim to the end of every prompt a Command Center orchestrator (or any session
dispatching a worker against a `triggers/*.md` file) sends to a subagent/worker. It codifies what
orchestrator sessions have been doing ad hoc into something any future session — or a fresh Claude
instance with no memory of this one — picks up automatically by following the pattern, not by
remembering a habit. It's also what `command-center-freshness-check.sh` (the `SubagentStop`
freshness hook) reads: a subagent that follows this footer produces exactly the signal that hook
checks for, and stays silent; one that doesn't will get flagged to the orchestrator as stale.

---

```
---
When you are done, before ending your turn:

1. Set this trigger's `status:` frontmatter field PRECISELY:
   - `completed` — ONLY if the work is truly done and there is no pending human step. If a human
     still needs to do something (review, merge, physical-device test, flip a config), that is
     NOT `completed` — use `in_progress` and say what's still needed.
   - `in_progress` — real progress made, but not finished, or finished-but-blocked-on-a-human-step.
   - `blocked` — cannot proceed without something else (a decision, another trigger, a resource).
   Do not leave it at a stale default (`pending`) if you did any work at all.

2. Fill in this trigger's `## Result` section with your actual findings — what you did, what you
   tested and how, what's still open. Be accurate, not optimistic: a wrong "done" here is worse
   than an honest "not done, here's why." This is read by both the mechanical dashboard and the
   freshness hook, and by whoever picks up the work next with zero other context.

3. Commit the trigger file (and any other changes) and PUSH — a completed-but-unpushed trigger is
   indistinguishable from an abandoned one to every other session/machine watching the KB. Commit
   implies push (standing fleet convention, see CLAUDE.md § Commit & Communication) unless you were
   explicitly told to hold work on a branch for review.

4. If your assignment was itself guardrailed to commit-local-never-push (e.g. a spawned
   `claude-worker` under `settings.worker.json`), say so explicitly in the Result section instead
   of silently leaving it uncommitted — "committed locally on branch X, NOT pushed per my
   dispatch's push restriction" is a fresh, accurate signal; silence is not.
---
```

## Why this exists

The command center only stayed current because the orchestrator session manually wrote ledger rows
and pushed trigger updates after every subagent finished — pure habit, not enforcement. See
[`the command center design doc`](../../../the command center design doc)
and the `command-center-freshness-check.sh` header comment for the enforcement half of this fix
(a non-blocking `SubagentStop` hook that nags the orchestrator, but never auto-decides trigger
status or auto-writes ledger rows itself — that stays a judgment call).
