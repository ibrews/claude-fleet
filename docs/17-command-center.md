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

### Phase board sourced from your roadmap doc (no double-editing)

Within the briefing, the **phase board** and the two **progress bigbars** are the kind of numbers
you already keep in a project's roadmap/status doc. Editing them in *both* the roadmap and
`briefing.json` is exactly how the two drift apart — and hand-typing a rolled-up percentage is how it
sits frozen for days while the phases move underneath it. So the engine derives both from one place:
put a machine-readable fenced ```phases block (JSON) in the doc named by `instance.json`'s
`content_source`, with one entry per phase — `id` / `name` / `subtitle` / `status` / `pct` / `state`,
plus a `weight` (relative size, default 1) and a `first_show` flag (is this phase on the critical path
to your first-milestone bigbar). Each cycle `lib/phase_sync.py`:

- **copies the phases verbatim** into `briefing.json`'s `phases` (the per-phase `pct` stays exactly as
  you authored it — no model, no interpretation), and
- **computes the two bigbars** as weighted means of the phase pcts (`to_first_show_pct` over the
  `first_show` phases, `full_roadmap_pct` over all of them). The bigbar number is never hand-typed, so
  it can't go stale — edit any phase `pct` and the relevant bar moves on the next cycle.

A bad or missing block leaves `briefing.json` untouched (the reason is logged). The phase board is
stamped with the roadmap doc's own `updated:` date, so its freshness reflects the source you actually
edit. Everything else in the briefing stays AI-authored at checkpoints as above.

Two things keep that phase board honest between edits, both automatic and both refusing to touch a
high-stakes number themselves:

- **Consistency nudges.** Each cycle the engine checks every phase for a `status`/`pct` contradiction
  (marked *proven* but under 100%, at 100% but not *proven*, *planned* but above 0%, *live* but 0%)
  and warns if the whole board has gone stale. These surface as a "suggestions only — nothing is
  auto-applied" callout under the phase board. They flag *that* a number looks wrong for a human to
  fix; they never guess what it should be.
- **Loop-safe narrative refresh (optional).** A cheap local model can keep the "where we are"
  one-liner and the human-action queue current on quiet, bookkeeping-only cycles (`run-loop.sh` calls
  `refresh_briefing_local.py --loop-mode`). Anything substantive is deliberately left for a human/AI
  checkpoint — the cheap model never auto-publishes a real narrative claim. Set
  `CC_NARRATIVE_REFRESH=0` to turn it off.

## Durable state (optional)

By default all generated state (ledger, dedup file, dashboard, briefing) stays local to whichever
machine runs the loop. For a project you want to survive a dead host, point `instance.json`'s
`state_root` at a dedicated git repo you control; `run-loop.sh` pulls it before each cycle and
commits+pushes it after. Recovery from a dead machine is then just: clone your KB, clone the state
repo, restart the loop. A `HALT` file at that repo's root halts *every* instance sharing it — pushed
from anywhere, including the GitHub web editor, it's a remote kill switch. This is opt-in — omit
`state_root` and the engine falls back to the plain local layout. See
`scripts/command-center/README.md` § "Durable state" for the exact setup.

State-repo git handling lives inside the engine (`lib/gitsync.py`): `cycle.py` pulls
(rebase + autostash) before each cycle and commit+pushes with rebase-retry after, auto-resolving
conflicts on regenerated `index.html` files and aborting fail-safe on anything human-authored.
This makes two writers safe — an always-on loop on one machine and manual `cycle.py` runs from a
session on another can no longer strand the clone mid-rebase. Opt out per-run with
`--no-git-sync`.

## The escalation ladder (open problems that can't be silently forgotten)

Briefing `problems[]` entries with `phase: "open"` may carry three extra fields: `owner`,
`next_check` (a date), and `flag_count`. The dashboard renders them as badges; the engine enforces
them — when a `next_check` date passes without the problem being re-checked, `cycle.py` fires a
`ladder_overdue` interrupt (once per title+date; bumping the date re-arms it). The convention the
fields encode: flag 1 = it's in the briefing; flag 2 = a direct ask has been drafted for the
owner; flag 3+ = escalate actively. The design premise: an open item flagged three times with no
movement is a process failure, and the machinery — not anyone's memory — should be what notices.

## Close-out fires itself

When the briefing's `status` becomes `"delivered"`, the next cycle materializes a `closeout.md`
checklist next to the briefing (credential rotation, publicity/attribution clearance, retro,
invoice/next-phase, asset archival) and fires a one-time interrupt. Post-delivery work is
predictable; it shouldn't wait to be remembered. File existence is the dedup, so it fires once
per project.

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

## Real worker spawning (v3, guardrailed, off by default)

`scripts/command-center/lib/spawn.py` can launch, reap, and kill real workers — but only through a
fail-closed gate stack, and **it starts in `propose` mode where nothing launches without your
explicit confirm.** Every launch must clear all of: mode gate → prior-art gate → concurrency cap →
cycle + real-$ budget → daily spawn cap → HALT (which also SIGTERMs live children). Two executor
tiers, cheapest-first: an `inference` tier (Ollama/Gemini/NIM — no agent-model budget, for
summarize/classify/draft subtasks) and a `claude-worker` tier (a headless `claude -p` locally or
over `ssh`, under `settings.worker.json` which denies all push/merge/deploy/delete —
*commit-local-never-push*, so a worker's output is a local branch you review, never a surprise push).

Flipping `spawn.mode` from `"propose"` to `"auto"` is the live-autonomy switch — a deliberate,
manual `policy.json` edit, never a code default. Ship decision-only first, watch propose-mode
proposals for a while, then graduate.

## Talking to it (v3)

Three surfaces onto one orchestrator:

- **`command_center_server.py`** — a small stdlib HTTP control agent that runs on the *same* host as
  the loop (spawning and reaping must be co-located: a worker's pid liveness is only checkable on the
  host that launched it). Token-gated (`~/.fleet-token` / `X-Fleet-Token`), tailnet-bound. Endpoints:
  `/cc/state`, `/cc/spawn`, `/cc/confirm`, `/cc/reject`, `/cc/halt`, `/cc/resume`, `/cc/message`.
- **`mcp-server/`** — a thin Claude Desktop MCP connector (`index.mjs`) that proxies to the control
  agent, so you can ask "what's the state of X?" / "spawn a worker to do Y" / "confirm that" from a
  chat window. Register it in `claude_desktop_config.json` (see `mcp-server/package.json`).
- **`master/`** — an optional always-on `cc-master` session (system prompt + loop wrapper) that arms
  a fleet-bus listener, so Telegram replies route to one persistent brain when you're mobile.

All three are read-only-until-you-say-go: they surface state and *propose*, and only launch on an
explicit confirm while `spawn.mode` is `propose`.

## What it deliberately does not do yet

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
