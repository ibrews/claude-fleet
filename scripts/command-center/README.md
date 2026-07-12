# Command Center — orchestrator engine

A persistent orchestrator for large, multi-session AI projects. Composes existing fleet
infrastructure (session-board, triggers/inbox, fleet-bus, kb-search + technique graph) rather than
rebuilding it. Full design + rationale:
[`intelligence/decisions/2026-07-12-command-center-orchestrator.md`](../../../intelligence/decisions/2026-07-12-command-center-orchestrator.md).

This directory is the **generic engine** — it knows nothing about any specific project. Per-project
state lives in `projects/<name>/command-center/instance.json` (see
`projects/your-project/command-center/` for the first instance).

## Files

| File | What |
|---|---|
| `policy.json` | Guardrail action classes (green/yellow/red) + budget caps. Edit to change limits — never hardcode numbers in the scripts. |
| `lib/guardrail.py` | Classifies an action against `policy.json`. Fails closed on unknown action types. |
| `lib/reconcile.py` | Parses `sessions/active/*.md`, `triggers/*.md`, `inbox/*.md` into a state model, filtered to an instance's keywords. |
| `lib/dispatch.py` | Creates trigger files / bus nudges for green actions. `spawn_worker` is decision-only in v1 — it does NOT launch a real process (see the module docstring for why). Refuses to write a build-shaped trigger with no `prior_art_summary` — see prior-art gate below. |
| `lib/prior_art.py` | The prior-art gate: `is_build_shaped()` heuristic + `check_trigger_*()`. A declaration gate, not a diligence guarantee — see module docstring. |
| `lib/dashboard.py` | Renders the state model to a self-contained, dark-mode-aware static `index.html`. |
| `lib/interrupt.py` | Evaluates the 5 interrupt conditions (blocked/done/decision/budget/anomaly), dedup'd against a `notified.json` so the same item doesn't re-ping forever. |
| `lib/ledger.py` | Append-only `orchestrator-log.jsonl` — every dispatch, interrupt, and cycle logged. |
| `cycle.py` | One full cycle: ingest → reconcile → dispatch → dashboard → interrupt → persist. Checks `HALT` first. |
| `run-loop.sh` | Always-on wrapper: `git pull`, run one cycle, sleep, repeat. Never auto-pushes (see comments). |
| `com.example.command-center.plist` | launchd `KeepAlive` template for your always-on host. |
| `settings.orchestrator.json` | Restricted `settings.json` for any Claude session the orchestrator invokes — hard permission-layer deny on push/merge/deploy/rm. |

## Prior-art gate

Two layers, deliberately redundant:

1. **`dispatch.py`'s own refusal** — any trigger the orchestrator writes for itself is checked at
   creation time; a build-shaped one with no `prior_art_summary` argument is refused (no file
   written) rather than silently dispatched. This is the only path that's *actually enforced*, but
   it only covers triggers the orchestrator authors.
2. **`prior-art-gate-check.sh`** (PreToolUse/Write hook) — the backstop for triggers a human or a
   non-orchestrator session writes directly, bypassing `dispatch.py` entirely. Fires a
   non-blocking reminder (`additionalContext`) pointing at kb-search +
   `projects/techniques-graph/master-index.md` when a new `triggers/*.md` file looks build-shaped
   and its `prior_art:` field is empty. **Soft by design** — the heuristic can confirm a field was
   *filled in*, not that a real search happened, so a hard block would just train sessions to type
   a throwaway string past it.

Run `python3 lib/prior_art.py` with no args to scan every real trigger in the KB and see the
current gap (as of this writing: 5 of 25 existing triggers are build-shaped and predate the field,
which is expected — it didn't exist before this).

**Installing the hook fleet-wide is a separate, deliberate step, not done as part of writing this
code.** `install-fleet-hooks.sh` now copies `prior-art-gate-check.sh` and `merge-settings.js`
registers it, but actually *running* the installer against a machine's live `~/.claude/settings.json`
should be a conscious choice (same as any other fleet hook rollout) — not something this session did
silently to Alex's own config.

## Kill switch

Drop a file named `HALT` (see `policy.json`'s `halt_file`) into the instance directory
(`projects/<name>/command-center/HALT`). Next cycle logs `halt_observed`, skips dispatch and
interrupts, but still refreshes the read-only dashboard. Remove the file to resume.

## Run one cycle manually

```bash
python3 cycle.py --instance ../../../projects/your-project/command-center/instance.json
python3 cycle.py --instance <path> --dry-run   # logs intended bus sends, doesn't actually send
```

## Install on your always-on host

Some machines block scheduled/launchd writes from a fully unattended session (sandbox or
automation policy) — if `launchctl load` hangs or errors silently, run this from an interactive
terminal on that machine instead of a headless/automated one.

```bash
cp scripts/command-center/com.example.command-center.plist ~/Library/LaunchAgents/
# edit __KB_ROOT__ and __INSTANCE_JSON_PATH__ placeholders in the copied plist first
launchctl load ~/Library/LaunchAgents/com.example.command-center.plist
tail -f /tmp/command-center.log
```

## Forking for a new project

1. Copy this `command-center/` directory as-is — it's generic.
2. Write a new `projects/<your-project>/command-center/instance.json` (copy
   `projects/your-project/command-center/instance.json` as a template — `name`, `keywords`,
   `tracked_workers`, paths).
3. Run one manual cycle (`--dry-run` first) to sanity-check the keyword filter actually matches
   your project's real triggers/sessions before trusting it unattended.
4. Point `CC_INSTANCE` at the new `instance.json` if running its own always-on loop, or extend
   `cycle.py`'s caller to loop over multiple instances (not built in v1 — one instance per loop
   process for now, deliberately simple).

## What v1 deliberately does NOT do yet

- **Does not spawn real worker processes.** `dispatch.decide_spawn()` proves the guardrail/cap math
  but never calls `subprocess` to launch a headless `claude -p` session. Wiring that is the next
  concrete step once Alex has seen this decision-only version run for a while — auto-launching
  sessions against a live project is a real resource/budget commitment worth watching first.
- **Does not detect subjective DECISION conditions.** No mechanical heuristic can reliably tell
  "this needs Alex's judgment" from frontmatter. `interrupt.py` exposes the condition but nothing
  currently writes it — a future richer reconcile pass, or a worker explicitly flagging its own
  ambiguity, would populate this.
- **Does not publish the dashboard.** Renders locally; hosting it needs a new private GitHub repo
  with Pages enabled (a repo-creation decision, not something to do silently mid-cycle).
- **Does not auto-commit/push its own state to the KB.** Generated state is gitignored and local to
  the running machine — see the `.gitignore` entry and `run-loop.sh`'s comments for why an earlier
  draft that did this was wrong.
