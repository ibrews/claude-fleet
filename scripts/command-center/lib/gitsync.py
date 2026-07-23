"""Safe git sync for the command-center state repo.

Why this exists (2026-07-23, Joby retro): two writers — the always-on run-loop
host and any interactive PM session running cycle.py by hand — kept colliding
on the state repo. run-loop.sh's bare `git pull --rebase || warn` would leave
the clone MID-REBASE (detached HEAD) on conflict and carry on; pushes had no
retry, so a hand-run push between the loop's pull and push was rejected. Every
collision got hand-resolved and none got fixed. This module makes both ends
safe and is called from cycle.py directly, so *every* caller inherits it.

Resolution policy:
- REGENERATED files (any */dashboard/index.html, the root index.html) conflict
  meaninglessly — both sides are machine output and the current cycle rewrites
  them anyway. Auto-resolve by taking the LOCAL side and continue the rebase.
- NARRATIVE/state files (briefing.json, state/*) are never auto-resolved:
  abort the rebase, keep local work intact, and report — fail-safe over
  fail-silent. The next cycle retries after a fresh pull.
"""
import os
import subprocess

GENERATED_BASENAMES = {"index.html"}


def _git(state_root, *args, check=False):
    return subprocess.run(["git", "-C", state_root, *args],
                          capture_output=True, text=True, check=check)


def _is_repo(state_root):
    return os.path.isdir(os.path.join(state_root, ".git"))


def _mid_rebase(state_root):
    g = os.path.join(state_root, ".git")
    return any(os.path.exists(os.path.join(g, d)) for d in ("rebase-merge", "rebase-apply"))


def _conflicted_files(state_root):
    out = _git(state_root, "diff", "--name-only", "--diff-filter=U").stdout
    return [f for f in out.splitlines() if f.strip()]


def _resolve_generated_or_abort(state_root, log):
    """Inside a conflicted rebase: auto-resolve generated files, abort on anything else."""
    conflicts = _conflicted_files(state_root)
    unresolvable = [f for f in conflicts if os.path.basename(f) not in GENERATED_BASENAMES]
    if unresolvable:
        _git(state_root, "rebase", "--abort")
        log(f"gitsync: rebase aborted — non-generated conflicts need a human: {unresolvable}")
        return False
    for f in conflicts:
        # During pull --rebase, --theirs = the local commit being replayed.
        _git(state_root, "checkout", "--theirs", "--", f)
        _git(state_root, "add", "--", f)
    r = subprocess.run(["git", "-C", state_root, "rebase", "--continue"],
                       capture_output=True, text=True,
                       env={**os.environ, "GIT_EDITOR": "true"})
    if r.returncode != 0:
        # A multi-commit rebase can conflict again on the next commit — recurse.
        if _mid_rebase(state_root):
            return _resolve_generated_or_abort(state_root, log)
        _git(state_root, "rebase", "--abort")
        log(f"gitsync: rebase --continue failed, aborted: {r.stderr.strip()[:200]}")
        return False
    return True


def pull(state_root, log=print):
    """Bring the clone current. Returns True if the tree is clean/current."""
    if not _is_repo(state_root):
        return True
    if _mid_rebase(state_root):  # leftover from a pre-fix crash — recover first
        log("gitsync: found leftover mid-rebase state, aborting it")
        _git(state_root, "rebase", "--abort")
    r = _git(state_root, "pull", "--rebase", "--autostash")
    if r.returncode == 0:
        return True
    if _mid_rebase(state_root):
        return _resolve_generated_or_abort(state_root, log)
    log(f"gitsync: pull failed (offline?): {r.stderr.strip()[:200]}")
    return False


def commit_push(state_root, message, log=print, retries=3):
    """Commit everything and push, rebasing+retrying on rejection."""
    if not _is_repo(state_root):
        return True
    _git(state_root, "add", "-A")
    staged = _git(state_root, "diff", "--cached", "--quiet")
    if staged.returncode == 0:
        return True  # nothing to commit
    c = _git(state_root, "commit", "-q", "-m", message)
    if c.returncode != 0:
        log(f"gitsync: commit failed: {c.stderr.strip()[:200]}")
        return False
    for attempt in range(retries):
        p = _git(state_root, "push", "-q")
        if p.returncode == 0:
            return True
        if not pull(state_root, log):  # rejected — rebase onto remote and retry
            return False
        log(f"gitsync: push rejected, rebased and retrying ({attempt + 1}/{retries})")
    log("gitsync: push still failing after retries — will ride out on a later cycle")
    return False
