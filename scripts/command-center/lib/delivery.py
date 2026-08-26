#!/usr/bin/env python3
"""Read-only Git and CI evidence for the Command Center delivery cockpit."""

import json
import os
import re
import subprocess
from datetime import datetime, timezone


GITHUB_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RED_CONCLUSIONS = {
    "action_required", "cancelled", "failure", "startup_failure", "stale", "timed_out",
}


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(args, *, cwd=None, timeout=10):
    try:
        result = subprocess.run(
            args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _git(path, *args):
    return _run(["git", "-C", path, *args], timeout=8)


def inspect_local_repo(config):
    """Inspect a checkout without fetching, committing, or changing refs."""
    path = os.path.expanduser(config.get("path", ""))
    result = {
        "name": config.get("name") or os.path.basename(path) or config.get("github", "repository"),
        "path": path,
        "source": "local Git snapshot (read-only; no fetch)",
        "available": False,
        "as_of": _now_iso(),
        "dirty": False,
        "dirty_entries": 0,
        "current_branch": "",
        "unintegrated_branches": [],
        "error": "",
    }
    if not path or not os.path.isdir(path):
        result["error"] = "checkout not present on this host"
        return result
    code, _, err = _git(path, "rev-parse", "--git-dir")
    if code:
        result["error"] = err or "not a Git repository"
        return result
    result["available"] = True

    _, branch, _ = _git(path, "branch", "--show-current")
    result["current_branch"] = branch or "detached"
    _, status, _ = _git(path, "status", "--porcelain=v1", "--untracked-files=normal")
    entries = [line for line in status.splitlines() if line.strip()]
    result["dirty_entries"] = len(entries)
    result["dirty"] = bool(entries)

    default_branch = config.get("default_branch", "main")
    candidates = [f"refs/remotes/origin/{default_branch}", f"refs/heads/{default_branch}"]
    base = ""
    for candidate in candidates:
        code, _, _ = _git(path, "show-ref", "--verify", "--quiet", candidate)
        if code == 0:
            base = candidate
            break
    if not base:
        result["error"] = f"default branch ref not found: {default_branch}"
        return result

    fmt = "%(refname:short)|%(upstream:short)|%(committerdate:iso8601-strict)"
    _, branches, _ = _git(path, "for-each-ref", f"--format={fmt}", "refs/heads/")
    for row in branches.splitlines():
        parts = row.split("|", 2)
        if len(parts) != 3:
            continue
        name, upstream, committed_at = parts
        if name == default_branch:
            continue
        code, count, _ = _git(path, "rev-list", "--count", f"{base}..{name}")
        try:
            unique_commits = int(count) if code == 0 else 0
        except ValueError:
            unique_commits = 0
        if unique_commits:
            result["unintegrated_branches"].append({
                "branch": name,
                "unique_commits": unique_commits,
                "upstream": upstream,
                "committed_at": committed_at,
                "no_upstream": not bool(upstream),
            })
    result["unintegrated_branches"].sort(
        key=lambda item: (item["committed_at"], item["branch"]), reverse=True
    )
    return result


def inspect_ci(github_slug):
    result = {
        "github": github_slug,
        "source": "GitHub Actions",
        "as_of": _now_iso(),
        "status": "unavailable",
        "workflows": [],
        "red": [],
        "error": "",
    }
    if not GITHUB_SLUG_RE.match(github_slug or ""):
        result["error"] = "invalid GitHub owner/repository slug"
        return result
    code, output, err = _run([
        "gh", "run", "list", "--repo", github_slug, "--limit", "50", "--json",
        "workflowName,status,conclusion,createdAt,updatedAt,url,headBranch,event",
    ], timeout=15)
    if code:
        result["error"] = err or "GitHub Actions query failed"
        return result
    try:
        runs = json.loads(output or "[]")
    except json.JSONDecodeError as exc:
        result["error"] = f"invalid GitHub response: {exc}"
        return result
    latest = {}
    for run in runs:
        name = run.get("workflowName") or "unnamed workflow"
        if name not in latest:
            latest[name] = run
    result["workflows"] = list(latest.values())
    result["red"] = [
        run for run in result["workflows"] if run.get("conclusion") in RED_CONCLUSIONS
    ]
    if result["red"]:
        result["status"] = "red"
    elif any(run.get("status") != "completed" for run in result["workflows"]):
        result["status"] = "running"
    elif result["workflows"]:
        result["status"] = "green"
    else:
        result["status"] = "no_runs"
    return result


def inspect_pull_requests(github_slug):
    if not GITHUB_SLUG_RE.match(github_slug or ""):
        return []
    code, output, _ = _run([
        "gh", "pr", "list", "--repo", github_slug, "--state", "open", "--limit", "30",
        "--json", "number,title,headRefName,isDraft,updatedAt,url,reviewDecision,statusCheckRollup",
    ], timeout=15)
    if code:
        return []
    try:
        return json.loads(output or "[]")
    except json.JSONDecodeError:
        return []


def collect(instance_config):
    """Collect evidence only for explicitly enabled projects.

    Explicit configuration prevents the fleet index from guessing repository
    ownership or hammering GitHub for dormant projects every cycle.
    """
    config = instance_config.get("delivery") or {}
    if not config.get("enabled"):
        return {"enabled": False, "repositories": [], "as_of": _now_iso()}
    repositories = []
    for repo_config in config.get("repositories", []):
        local = inspect_local_repo(repo_config)
        github = repo_config.get("github", "")
        repositories.append({
            **local,
            "github": github,
            "ci": inspect_ci(github) if github else {
                "status": "unavailable", "workflows": [], "red": [],
                "error": "no GitHub repository configured", "as_of": _now_iso(),
            },
            "pull_requests": inspect_pull_requests(github) if github else [],
        })
    return {"enabled": True, "repositories": repositories, "as_of": _now_iso()}


def summarize(delivery_state):
    repos = delivery_state.get("repositories", [])
    return {
        "red_ci": sum(repo.get("ci", {}).get("status") == "red" for repo in repos),
        "ci_unavailable": sum(repo.get("ci", {}).get("status") == "unavailable" for repo in repos),
        "dirty_repos": sum(bool(repo.get("dirty")) for repo in repos),
        "unintegrated_branches": sum(len(repo.get("unintegrated_branches", [])) for repo in repos),
        "open_pull_requests": sum(len(repo.get("pull_requests", [])) for repo in repos),
    }
