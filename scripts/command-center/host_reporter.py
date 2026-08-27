#!/usr/bin/env python3
"""Publish read-only repository evidence from the machine that owns each checkout.

The report is a durable machine fact, not a command channel. It never fetches,
checks out, commits in a product repository, or executes project code.
"""
import argparse
import glob
import json
import os
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ENGINE_DIR, "lib"))
import delivery  # noqa: E402
import gitsync  # noqa: E402

REPORT_SCHEMA = "host-evidence/v1"


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover_repository_configs(kb_root, machine):
    """Return explicitly assigned repositories; never guess ownership from paths."""
    repositories = []
    pattern = os.path.join(kb_root, "projects", "*", "command-center", "instance.json")
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path) as handle:
                instance = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        delivery_config = instance.get("delivery") or {}
        if not delivery_config.get("enabled"):
            continue
        for repository in delivery_config.get("repositories", []):
            if repository.get("host") != machine:
                continue
            repositories.append({
                **repository,
                "project": instance.get("name", ""),
            })
    return repositories


def build_report(kb_root, machine):
    repositories = []
    for config in discover_repository_configs(kb_root, machine):
        snapshot = delivery.inspect_local_repo(config)
        repositories.append({
            **snapshot,
            "project": config["project"],
            "github": config.get("github", ""),
        })
    return {
        "schema": REPORT_SCHEMA,
        "machine": machine,
        "generated_at": _now_iso(),
        "repositories": repositories,
    }


def write_report(report, state_root):
    report_dir = os.path.join(os.path.expanduser(state_root), "host-evidence")
    os.makedirs(report_dir, exist_ok=True)
    destination = os.path.join(report_dir, f"{report['machine']}.json")
    handle, temporary = tempfile.mkstemp(prefix=".host-evidence-", suffix=".json", dir=report_dir)
    try:
        with os.fdopen(handle, "w") as output:
            json.dump(report, output, indent=2, sort_keys=True)
            output.write("\n")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def _git(state_root, *args):
    return subprocess.run(
        ["git", "-C", state_root, *args], text=True, capture_output=True, check=False,
    )


def publish_report(report, state_root, log=print, retries=3):
    """Commit only this host's evidence file, preserving unrelated state-repo edits."""
    state_root = os.path.expanduser(state_root)
    if not os.path.isdir(os.path.join(state_root, ".git")):
        raise RuntimeError(f"state root is not a Git clone: {state_root}")
    if not gitsync.pull(state_root, log):
        raise RuntimeError("state repo pull failed; report was not published")
    destination = write_report(report, state_root)
    relative = os.path.relpath(destination, state_root)
    changed = _git(state_root, "status", "--porcelain", "--", relative).stdout.strip()
    if not changed:
        return destination
    added = _git(state_root, "add", "--", relative)
    if added.returncode:
        raise RuntimeError(f"host report staging failed: {added.stderr.strip()[:240]}")
    commit = _git(
        state_root, "commit", "-q", "-m",
        f"evidence: {report['machine']} {report['generated_at']}", "--only", "--", relative,
    )
    if commit.returncode:
        raise RuntimeError(f"host report commit failed: {commit.stderr.strip()[:240]}")
    for attempt in range(retries):
        pushed = _git(state_root, "push", "-q")
        if pushed.returncode == 0:
            return destination
        if not gitsync.pull(state_root, log):
            break
        log(f"host reporter: push rejected, rebased and retrying ({attempt + 1}/{retries})")
    raise RuntimeError("host report push failed after retries")


def main():
    parser = argparse.ArgumentParser(description="Publish Command Center host Git evidence")
    parser.add_argument("--kb-root", default=os.path.expanduser("~/knowledge"))
    parser.add_argument("--state-root", default=os.path.expanduser("~/command-center-state"))
    parser.add_argument(
        "--machine", default=os.environ.get("CC_MACHINE") or socket.gethostname().split(".")[0].lower(),
    )
    parser.add_argument("--publish", action="store_true", help="commit and push the report")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if not delivery.HOST_ID_RE.match(args.machine):
        parser.error("machine must contain only letters, numbers, dot, underscore, or hyphen")
    report = build_report(os.path.expanduser(args.kb_root), args.machine)
    destination = (
        publish_report(report, args.state_root) if args.publish
        else write_report(report, args.state_root)
    )
    if args.as_json:
        print(json.dumps({**report, "destination": destination}, indent=2))
    else:
        action = "published" if args.publish else "wrote"
        print(f"{action} {len(report['repositories'])} repository snapshot(s) -> {destination}")


if __name__ == "__main__":
    main()
