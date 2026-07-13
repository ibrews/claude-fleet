#!/usr/bin/env python3
"""Interrupt-the operator logic for the Command Center orchestrator.

Evaluates the 5 interrupt conditions (blocked / done / decision / budget /
anomaly) against the current state model, but ONLY fires on NEW
occurrences — a small "seen" file in the instance state dir tracks which
blocked/done/anomaly ids and which budget thresholds have already been
notified, so the same known blocker doesn't re-ping every 30 minutes
forever. This is the mechanism that keeps the orchestrator from becoming
just another noisy session.

DECISION does not try to infer "this is a genuinely subjective either/or"
from prose or frontmatter — that classification requires judgment, and a
keyword/pattern guess would either spam false positives or silently miss
real decisions (see intelligence/decisions/2026-07-13-command-center-decision-interrupt.md
for the tradeoff and why an explicit signal won out over a mechanical
scan). Instead it detects an EXPLICIT, worker-authored DECISION_NEEDED.md
file in the instance dir (same level as HALT/briefing.json — see
cycle.py's resolve_paths) — any worker, or a future richer reconcile
pass, writes it when it hits a choice it can't resolve itself. Dedup is
by content hash, not id: editing the file (a new question, updated
options) re-notifies; clearing/deleting it after the operator answers is the
resolution signal, the same convention as the HALT kill switch.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import dispatch  # noqa: E402
import ledger as ledger_mod  # noqa: E402


def load_seen(state_dir):
    path = os.path.join(state_dir, "notified.json")
    default = {"blocked": [], "done": [], "anomaly": [], "budget_thresholds_hit": [], "decision": []}
    if not os.path.exists(path):
        return default
    with open(path) as f:
        data = json.load(f)
    # Backward-compat: older notified.json files predate the "decision" key.
    for k, v in default.items():
        data.setdefault(k, v)
    return data


def save_seen(state_dir, seen):
    path = os.path.join(state_dir, "notified.json")
    with open(path, "w") as f:
        json.dump(seen, f, indent=2)


def evaluate(state, seen, ledger_path, policy):
    """Returns list of {condition, message} for NEW occurrences only. Mutates seen in place."""
    events = []

    # BLOCKED — new blocked triggers since last cycle
    for t in state["triggers_blocked"]:
        if t["id"] not in seen["blocked"]:
            seen["blocked"].append(t["id"])
            events.append({
                "condition": "blocked",
                "message": f'[{state["instance"]}] BLOCKED: "{t["title"]}" ({t["target"]}) — {t["file"]}',
            })

    # DONE — new completed triggers since last cycle
    for t in state["triggers_done"]:
        if t["id"] not in seen["done"]:
            seen["done"].append(t["id"])
            events.append({
                "condition": "done",
                "message": f'[{state["instance"]}] DONE: "{t["title"]}" (by {t.get("claimed_by") or "?"})',
            })

    # ANOMALY — new stale/dead session still holding a real claim
    for s in state["sessions_stale_or_dead"]:
        if not s.get("claim"):
            continue
        aid = s["file"]
        if aid not in seen["anomaly"]:
            seen["anomaly"].append(aid)
            reason = "process gone" if not s["pid_alive"] else "stale heartbeat"
            events.append({
                "condition": "anomaly",
                "message": (
                    f'[{state["instance"]}] ANOMALY: {s["machine"]} claims "{s["claim"]}" but {reason} '
                    f'({s["heartbeat_age_min"]}m) — singleton may be free, verify before reclaiming'
                ),
            })

    # DECISION — explicit, worker-authored DECISION_NEEDED.md (see module docstring).
    # Presence alone isn't enough to dedup (the file can be re-edited with a new
    # question) — hash the content so an unchanged file doesn't re-ping every cycle,
    # but an edited one (or a fresh file after a prior one was cleared) does.
    decision_path = state.get("decision_needed_file")
    if decision_path:
        with open(decision_path) as f:
            content = f.read()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
        if content_hash not in seen["decision"]:
            seen["decision"].append(content_hash)
            summary = next(
                (line.strip().lstrip("#").strip() for line in content.splitlines() if line.strip()),
                "(see file for details)",
            )
            events.append({
                "condition": "decision",
                "message": f'[{state["instance"]}] DECISION: {summary} — see {decision_path}',
            })

    # BUDGET — 80%/100% cycle-count thresholds, each fires once per day
    budget_pct = ledger_mod.budget_pct_today(ledger_path, policy["budget"]["max_cycles_per_day"])
    today = __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime())
    for threshold in (policy["budget"]["warn_threshold_pct"], policy["budget"]["stop_threshold_pct"]):
        key = f"{today}:{threshold}"
        if budget_pct >= threshold and key not in seen["budget_thresholds_hit"]:
            seen["budget_thresholds_hit"].append(key)
            events.append({
                "condition": "budget",
                "message": f'[{state["instance"]}] BUDGET at {budget_pct}% of daily cycle cap (threshold {threshold}%)',
            })

    return events


def format_digest(state, ledger_path, policy):
    budget_pct = ledger_mod.budget_pct_today(ledger_path, policy["budget"]["max_cycles_per_day"])
    return (
        f'[{state["instance"]}] Daily digest — '
        f'{len(state["triggers_in_flight"])} in flight, '
        f'{len(state["triggers_blocked"])} blocked, '
        f'{len(state["triggers_done"])} done recently, '
        f'{len(state["sessions_live"])} live sessions, '
        f'{len(state["inbox_open"])} open inbox items, '
        f'budget {budget_pct}% today.'
    )


def send_all(events, fleet_bus_py, session, policy, dry_run=False):
    """Sends each event via bus_nudge(to_human=True). Returns list of results."""
    results = []
    for e in events:
        cls, out, reason = dispatch.bus_nudge(
            fleet_bus_py, to="human", body=e["message"], session=session,
            policy=policy, to_human=True, dry_run=dry_run,
        )
        results.append({**e, "classification": cls, "result": reason})
    return results
