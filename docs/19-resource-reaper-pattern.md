---
title: "The Resource Reaper Pattern"
updated: 2026-08-16
tags: [fleet, hygiene, disk-space]
---

# The Resource Reaper Pattern

A fleet of Claude Code sessions creates a lot of per-task resources: a worktree per
branch, a simulator or emulator per test scenario, a container per sandboxed run, a
scratch database per experiment. Every one of those is cheap to create and completely
reasonable to create — that's the whole point of isolating concurrent work (see
[docs/14-concurrent-sessions.md](14-concurrent-sessions.md)). None of them has a natural
end-of-life hook. A session finishes its task, ends, and the resource it made just sits
there.

None of that is a bug in any one session. It's what happens when creation is cheap,
frequent, and distributed across many independent sessions, and deletion is nobody's job
in particular. Left alone it becomes real disk pressure, real memory pressure, or just a
device/container list nobody can navigate anymore.

---

## The Trap: "Idle" and "Abandoned" Look the Same

The obvious fix — a cron job that deletes anything untouched for N days — is also the
fix most likely to delete someone's actual work. A worktree a session is mid-read on and
a worktree from a task that finished last week can have the *exact same* filesystem
signature: clean tree, branch merged, nothing modified recently. A freshly created
resource with zero activity yet looks identical to a genuinely stale one from a
timestamp alone.

**Recency is a hint, not proof.** A safe reaper needs at least one signal that's
independent of "how long since something touched this," and it needs to default to
*keeping* a resource whenever that signal is unavailable or ambiguous — never to
deleting on a guess.

---

## The Shape

Every reaper built against this pattern shares five properties, regardless of what
resource it manages:

1. **Ships dry-run first.** The first version of any reaper writes a report of what it
   *would* do and changes nothing. It only goes live after a human has read a few days
   of reports and confirmed the candidates it's flagging are actually safe to remove.
2. **At least one liveness signal independent of recency.** For a filesystem resource,
   that's typically `lsof -d cwd` — is any live process's working directory inside it
   right now? For a resource tracked on the [session board](14-concurrent-sessions.md),
   it's a heartbeat-fresh `claim:` entry naming the resource. Recency alone (a
   timestamp, an mtime) is never sufficient on its own.
3. **Unknown state means keep, not delete.** If the liveness check can't run, or the
   idle-time reference file is missing, the reaper skips that resource and says so in
   the report. Guessing safe is how you lose someone's work.
4. **Only destroys the disposable half.** A worktree *directory* is disposable; the
   *branch* it points at is not — deleting the branch destroys the evidence that
   unmerged work ever existed. Whatever your resource is, work out which part is truly
   replaceable (recreate in seconds, no data lost) and only ever touch that part.
5. **Deterministic, no AI call.** A reaper is a script, not an agent — it runs on a
   schedule without a model in the loop, cheap enough to run daily (or hourly) without
   anyone thinking about it.

---

## Reference Implementation: `scripts/worktree-reaper.sh`

[`scripts/worktree-reaper.sh`](../scripts/worktree-reaper.sh) applies the pattern to the
git worktrees created per [docs/14](14-concurrent-sessions.md)'s isolation guidance. It
reads a list of repos, and for each worktree it finds:

- Skips it if a live process's `cwd` is anywhere inside it (`lsof`-based).
- Skips it if it has uncommitted **tracked** changes (ignored build output doesn't
  count).
- Compares the branch tip against `git ls-remote origin` — not the local `origin/<b>`
  ref, which can be stale and make a pushed branch look local-only.
- Only removes a worktree if its branch tip is fully merged into the default branch, or
  is byte-identical to what's already on origin, or was squash-merged (checked via
  `git cherry`'s patch-id matching).
- Removes the **directory only**, via `git worktree remove` — never `rm -rf`, which has
  no dirty-tree refusal and no undo. The branch is never deleted.
- Reports every branch still carrying unmerged commits, every run, even when nothing was
  reaped — a backlog that isn't surfaced regrows silently.

```bash
DRY_RUN=1 bash scripts/worktree-reaper.sh    # report only (the default)
DRY_RUN=0 bash scripts/worktree-reaper.sh    # live — removes qualifying directories
```

Configure which repos it watches in `state/worktree-reaper-repos.txt` (one path per
line, `#` comments allowed):

```
# state/worktree-reaper-repos.txt
/path/to/your/repo-one
/path/to/your/repo-two
```

---

## Adapting It to a Different Resource

The mechanics change per resource type, but the shape doesn't. A few notes from porting
this pattern beyond git worktrees:

- **Pick the right "last used" reference.** Creation time is nearly always the wrong
  proxy — it tells you nothing about last use. Look for something the resource itself
  touches on every real use: a runtime lock file, a PID file, a socket, a `var/run`-style
  directory that gets rewritten on start. Verify it against a known-fresh and a
  known-stale instance before trusting it — a slow recursive scan for "the newest file
  anywhere inside" is usually both too slow to run daily and too noisy (backup tools and
  indexers touch files you don't care about).
- **Add the session-board claim check when the resource can be claimed there.** A
  heartbeat-fresh `claim:` entry (see [docs/14](14-concurrent-sessions.md)) naming the
  resource protects it, on top of whatever process-level liveness check you have — a
  session can hold a resource deliberately (a booted device it's mid-test on, say)
  without a process literally `cwd`'d into it.
- **Never build a bare idle-timer for a resource that's sometimes idle by design.** A
  process pinned in memory on purpose, or a long build that legitimately sits at near-zero
  CPU for stretches, will look exactly like an abandoned one to a naive timer. Any such
  resource needs an explicit exemption checked *before* the idle heuristic runs, not
  after.

## Rollout Checklist

- [ ] Write the report-only version first; point it at real data.
- [ ] Read the reports for a few days — do the "would reap" candidates match what you'd
      delete by hand?
- [ ] Run it live once, supervised, and verify the resource you expected to free up
      (disk, memory, a device list) actually changed by roughly the amount you expected.
- [ ] Only then schedule it unattended (`cron`, `launchd`, or your platform's task
      scheduler — see [docs/07-hooks.md](07-hooks.md) for the fleet's general approach to
      scheduled/triggered scripts).
