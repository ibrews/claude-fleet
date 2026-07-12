# Command Center

A persistent orchestrator for a large, multi-session project running across your fleet. One
always-on loop reconciles the real state of a project (who's working on what, what's blocked, what
just finished) from the primitives this repo already gives you — the inbox system, the session
board, the session bus — and pings you only when something actually needs your attention.

This exists for a specific failure mode: a project spans dozens of Claude Code sessions over weeks,
and the same problem gets independently re-solved two or three times in different corners of it
because nobody thought to check whether it was already handled somewhere else. The Command Center
is a **prior-art gate** plus a **reconciliation loop** plus a **guardrailed dispatcher** — not a new
communication channel (it composes the ones you already have).

## Where this fits

| | Inbox System (docs 05) | Session Bus (docs 16) | Command Center (this doc) |
|---|---|---|---|
| What it is | Async task passing | Real-time tap-on-the-shoulder | A standing loop that reconciles + reports |
| Runs continuously? | No — checked per session | No — only while armed | Yes, on a schedule |
| Talks to you? | Via Telegram, per-event | No | Only on blocked/done/decision/budget/anomaly, plus a daily digest |
| Scope | One task | One message | A whole project's state across every worker |

The Command Center doesn't replace the inbox or the bus — it reads both, plus your session board, to
build one picture, and it dispatches new work through the same inbox trigger format you already use.

## Architecture

```
you                                                              orchestrator loop (always-on host)
 │  goal / interrupt                                              ┌─────────────────────────────┐
 └──────────────────────────────────────────────────────────────▶ │ 1 ingest  → 2 reconcile       │
                                                                   │ 3 dispatch → 4 dashboard      │
                                          reply via Telegram ◀──── │ 5 interrupt-check → 6 persist │
                                                                   └─────────────────────────────┘
                                                                       │ reads/writes
                                                          session board · triggers/inbox · state files
```

Every cycle: pull the latest state, reconcile it into done/in-flight/blocked, dispatch anything
green-lit under the guardrail policy, regenerate a static dashboard (plus a fleet-wide index if
you're running more than one instance), check whether you need to be interrupted (plus a daily
digest), and persist. All state lives in plain files — a crash or restart just re-reads them, no
database.

## The dashboard is a briefing, not a status mirror

The dashboard renders two independent layers, each with its own visible staleness stamp:

- **Mechanical** — sessions, open/blocked/done triggers, anomalies, inbox items. Regenerated every
  cycle straight from `reconcile.py`'s state model. Always current, never lies about its own age.
- **Briefing** (`briefing.json`) — the narrative a cold reader needs: a north star, per-phase
  progress bars, a "where we are" one-liner, topic Q&As, the biggest unsolved problems, ranked
  recommendations, and a checkpoint timeline. A script can't write "what's the latest on the auth
  migration" — this layer is **AI-authored at checkpoints** by a session with real project context,
  never by the mechanical cycle. The dashboard shows a staleness chip once it's more than a few days
  old, so nobody mistakes a stale narrative for current truth.

If `briefing.json` doesn't exist yet, the dashboard degrades to mechanical-only with a hint — a
fresh fork works immediately, the briefing is additive once someone writes one.

## Durable state (optional)

By default all generated state (ledger, dedup file, dashboard, briefing) stays local to whichever
machine runs the loop. For a project you want to survive a dead host, point `instance.json`'s
`state_root` at a dedicated git repo you control; `run-loop.sh` pulls it before each cycle and
commits+pushes it after. Recovery from a dead machine is then just: clone your KB, clone the state
repo, restart the loop. A `HALT` file at that repo's root halts *every* instance sharing it — pushed
from anywhere, including the GitHub web editor, it's a remote kill switch. This is opt-in — omit
`state_root` and the engine falls back to the plain local layout. See
`scripts/command-center/README.md` § "Durable state" for the exact setup.

## Guardrails

Every action the loop can take is classified **green** (autonomous), **yellow** (act, then notify),
or **red** (never autonomous — ping and wait), in one small `policy.json` you edit directly rather
than buried in code:

- **Green:** read state, dispatch a trigger, nudge a live worker, regenerate the dashboard, spawn a
  worker *within a hard concurrency + budget cap*.
- **Yellow:** open a PR (never merge).
- **Red:** push or merge to a shared/main branch, deploy, delete anything, spawn beyond the cap,
  exceed the budget.

A committed `HALT` file (or a `HALT` trigger) stops all dispatch on the next cycle without killing
the process — the dashboard keeps refreshing so you can still see state while paused. Every
dispatch, interrupt, and budget tick is appended to a local, never-rewritten ledger.

**The interrupt conditions are deliberately narrow:** BLOCKED (a red action or a real decision is
needed), DONE (a milestone finished), DECISION (a genuinely subjective call — surfaced with options,
not left open-ended), BUDGET (a threshold crossed), ANOMALY (a stale claim, a dead worker holding a
singleton). Everything else, the loop reconciles silently. Each condition also dedupes against a
small `notified.json` so the same known blocker doesn't re-ping you every cycle forever.

## The prior-art gate

The re-litigation failure this whole thing exists to catch can't be reliably detected — a script
can't tell whether you actually searched, only whether you *said* you did. So the gate is a
declaration, not a guarantee: any build-shaped trigger (title/task text like "implement", "build",
"design", "from scratch") needs a `prior_art:` field filled in before it's dispatched. The
orchestrator's own dispatcher refuses to write one without it; a soft, non-blocking hook reminds you
if you write one by hand and forget. This won't catch someone typing a throwaway string past it — it
converts "nobody thought to check" into "you have to say what you checked," which is the actual gap
it's aimed at.

## Setup

1. Copy `scripts/command-center/` into your KB checkout — it's generic, no project-specific code.
2. Write `projects/<your-project>/command-center/instance.json` — the whole per-project config
   surface: a `name`, a list of `keywords` to filter your triggers/sessions to this project, and
   optionally a `tracked_workers` roster (name/repo/note) so specific named workers show up
   explicitly on the dashboard instead of buried in raw trigger lists.
3. Run one cycle by hand first, with `--dry-run`, and read the output before trusting it unattended:
   ```bash
   python3 scripts/command-center/cycle.py --instance projects/<your-project>/command-center/instance.json --dry-run
   ```
4. Once it looks right, install it as an always-on loop — `scripts/command-center/run-loop.sh` under
   `scripts/command-center/com.example.command-center.plist` (launchd `KeepAlive`; adapt for
   systemd/Task Scheduler on other platforms). See `scripts/command-center/README.md` for the full
   file-by-file breakdown and the exact install steps.
5. Optional: add `"state_root"` to `instance.json` and point a dedicated git repo at
   `CC_STATE_ROOT` if you want generated state (ledger, dashboard, briefing) to survive this
   machine dying — see `scripts/command-center/README.md` § "Durable state".

## What it deliberately does not do yet

- **Doesn't launch real worker processes.** Spawning is guardrail-gated and logged (`WOULD SPAWN` /
  `REFUSED`, with the cap math shown), but wiring an actual `claude -p` subprocess launch is left as
  your next step — worth watching the decision-only version run for a while first.
- **Doesn't detect subjective decisions mechanically.** No heuristic can reliably tell "this needs a
  human's judgment" from trigger text. The condition exists in the interrupt logic; something has to
  populate it (a worker flagging its own ambiguity, or a richer reconciliation pass you add).
- **Doesn't auto-publish its own dashboard.** It generates a self-contained static `index.html`;
  hosting it (GitHub Pages, Cloudflare Pages, or just opening the file) is your call. Note if you
  want it on a *private* repo's Pages: that requires a paid GitHub plan (Pro/Team/Enterprise) — a
  free-tier private repo can't serve Pages at all.
- **Doesn't auto-push its own state to your KB repo.** Generated ledger/dashboard/HALT files are
  meant to stay local to whichever machine runs the loop — auto-pushing them on every cycle would
  itself be exactly the kind of unattended write to a shared branch the guardrails above forbid the
  orchestrator from doing to your project's actual work.
