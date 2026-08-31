#!/usr/bin/env python3
"""Zero-token external pulse for the authoritative fleet manager.

Healthy ticks read files and Fleet Bus state only. A frontier manager is nudged
only when an actionable state appears or a prior nudge went unanswered past the
retry window. No LLM is called by this process.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(ENGINE_DIR, "lib")
sys.path.insert(0, LIB_DIR)
import session_health  # noqa: E402
import work_items  # noqa: E402


HOLDER_RE = re.compile(r"held by\s+([^/\s]+)/([^\s]+)")


def _run(args, timeout=20):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def role_state(fleet_bus, role):
    code, out, err = _run(["python3", fleet_bus, "whois", role])
    match = HOLDER_RE.search(out)
    return {
        "role": role, "live": code == 0 and "liveness: LIVE" in out,
        "machine": match.group(1) if match else "",
        "session_id": match.group(2) if match else "",
        "detail": out or err,
    }


def board_age_minutes(kb_root):
    path = os.path.join(kb_root, "sessions", "MANAGER-BOARD.md")
    code, out, _ = _run(["git", "-C", kb_root, "log", "-1", "--format=%ct", "--", path])
    try:
        return round((time.time() - int(out)) / 60.0, 1) if code == 0 else None
    except ValueError:
        return None


def _due(value):
    try:
        return date.fromisoformat(str(value)[:10]) <= date.today()
    except ValueError:
        return False


def worker_context(item, kb_root):
    session_id = item.get("session_id") or ""
    machine = (item.get("machine") or "").lower()
    if not session_id or not machine:
        return None
    warning_at = min(int(item.get("rollover_at") or 500000) - 50000, 450000)
    rollover_at = int(item.get("rollover_at") or 500000)
    context_limit = int(item.get("context_limit") or 600000)
    if machine == "your-laptop":
        return session_health.inspect_session(
            "~/.claude/projects", session_id, warning_at=warning_at,
            rollover_at=rollover_at, context_limit=context_limit,
        )
    script = os.path.join(
        "~/knowledge", "departments", "engineering", "command-center", "lib",
        "session_health.py",
    )
    code, out, _ = _run([
        "ssh", machine, "python3", script, session_id,
        "--warning-at", str(warning_at), "--rollover-at", str(rollover_at),
        "--context-limit", str(context_limit),
    ])
    if code:
        return {"session_id": session_id, "status": "unavailable", "machine": machine}
    try:
        result = json.loads(out)
        result["machine"] = machine
        return result
    except json.JSONDecodeError:
        return {"session_id": session_id, "status": "unavailable", "machine": machine}


def build_snapshot(kb_root, fleet_bus, role, *, project="", manager_stale_minutes=20):
    role = role_state(fleet_bus, role)
    items = [item for item in work_items.scan(kb_root)
             if item["status"] not in work_items.TERMINAL_STATUSES
             and (not project or item.get("project") == project)]
    board_age = board_age_minutes(kb_root)
    reasons = []
    if items and not role["live"]:
        reasons.append("manager role has active work but no live holder")
    if items and board_age is not None and board_age >= manager_stale_minutes:
        reasons.append(f"manager checkpoint is {board_age:.0f}m old")
    due = [item["id"] for item in items if item["status"] == "blocked" and _due(item.get("next_check"))]
    if due:
        reasons.append(f"blocked next-check due: {', '.join(due[:5])}")

    worker_contexts = []
    for item in items:
        health = worker_context(item, kb_root)
        if not health:
            continue
        health["task_id"] = item["id"]
        worker_contexts.append(health)
        if health.get("status") == "warning":
            reasons.append(
                f"{item['id']} context is {health.get('context_tokens')} tokens; prepare successor"
            )
        elif health.get("status") == "rollover":
            reasons.append(
                f"{item['id']} context is {health.get('context_tokens')} tokens; checkpoint and roll over now"
            )

    context = None
    if role["machine"] == "your-laptop" and role["session_id"]:
        context = session_health.inspect_session(
            "~/.claude/projects", role["session_id"], warning_at=450000,
            rollover_at=520000, context_limit=600000,
        )
        if context["status"] == "warning":
            reasons.append(
                f"manager context is {context['context_tokens']} tokens; prepare rollover"
            )
        elif context["status"] == "rollover":
            reasons.append(
                f"manager context is {context['context_tokens']} tokens; rollover now"
            )

    task_facts = [{
        key: item.get(key) for key in (
            "id", "status", "owner", "claimed_by", "session_id", "machine",
            "next_check", "executor", "model", "thinking", "rollover_at",
        )
    } for item in sorted(items, key=lambda item: item["id"])]
    stable = {"role": {k: role[k] for k in ("live", "machine", "session_id")},
              "tasks": task_facts, "reasons": reasons}
    fingerprint = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        **stable, "fingerprint": fingerprint, "active_count": len(items),
        "board_age_minutes": board_age, "manager_context": context,
        "worker_contexts": worker_contexts,
    }


def load_state(path):
    try:
        with open(os.path.expanduser(path)) as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path, state):
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w") as handle:
        json.dump(state, handle, indent=2)
    os.replace(temporary, path)


def should_nudge(snapshot, previous, *, retry_minutes=60, force=False):
    if not snapshot["reasons"]:
        return False, "healthy or no actionable transition"
    if force or snapshot["fingerprint"] != previous.get("fingerprint"):
        return True, "actionable state changed"
    last_nudge = int(previous.get("last_nudge_epoch") or 0)
    if time.time() - last_nudge >= retry_minutes * 60:
        return True, f"prior nudge unanswered for {retry_minutes}m"
    return False, "same actionable state is inside retry cooldown"


def send_nudge(fleet_bus, role, reasons, sender="manager-pulse"):
    body = (
        "EXTERNAL MANAGER PULSE — reconcile now: " + "; ".join(reasons) +
        ". Use the durable work-item records; perform the idle-roster sweep; checkpoint evidence."
    )
    return _run([
        "python3", fleet_bus, "send", "--to-role", role, "--body", body,
        "--session", sender, "--require-live",
    ])


def main():
    parser = argparse.ArgumentParser(description="Run one zero-token fleet-manager pulse")
    parser.add_argument("--kb-root", default=os.path.expanduser("~/knowledge"))
    parser.add_argument("--role", default="night-manager")
    parser.add_argument("--project", default="")
    parser.add_argument("--state-file", default="~/.claude/manager-pulse-state.json")
    parser.add_argument("--manager-stale-minutes", type=int, default=20)
    parser.add_argument("--retry-minutes", type=int, default=60)
    parser.add_argument("--prime", action="store_true", help="record baseline without sending")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    fleet_bus = os.path.join(
        args.kb_root, "departments", "engineering", "fleet-tools", "fleet_bus.py",
    )
    snapshot = build_snapshot(
        args.kb_root, fleet_bus, args.role, project=args.project,
        manager_stale_minutes=args.manager_stale_minutes,
    )
    previous = load_state(args.state_file)
    send, reason = should_nudge(snapshot, previous, retry_minutes=args.retry_minutes, force=args.force)
    result = {"send": send and not args.prime, "reason": reason, "snapshot": snapshot}
    if send and not args.prime and not args.dry_run:
        code, out, err = send_nudge(fleet_bus, args.role, snapshot["reasons"])
        result["delivery"] = {"exit_code": code, "output": out or err}
        if code != 0:
            print(json.dumps(result, indent=2))
            raise SystemExit(code)
    if not args.dry_run:
        save_state(args.state_file, {
            "fingerprint": snapshot["fingerprint"],
            "last_checked_epoch": int(time.time()),
            "last_nudge_epoch": (
                int(time.time()) if result["send"] else previous.get("last_nudge_epoch", 0)
            ),
        })
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
