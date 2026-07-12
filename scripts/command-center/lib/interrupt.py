#!/usr/bin/env python3
"""Interrupt-Alex logic for the Command Center orchestrator.

Evaluates the 5 interrupt conditions (blocked / done / decision / budget /
anomaly) against the current state model, but ONLY fires on NEW
occurrences — a small "seen" file in the instance state dir tracks which
blocked/done/anomaly ids and which budget thresholds have already been
notified, so the same known blocker doesn't re-ping every 30 minutes
forever. This is the mechanism that keeps the orchestrator from becoming
just another noisy session.

DECISION is deliberately a stub in v1: detecting "this is a genuinely
subjective either/or a worker can't resolve" from frontmatter alone isn't
a mechanical check — it requires judgment. v1 exposes the hook (a
DECISION_NEEDED.md file in the instance dir that any worker or a future
richer reconcile pass can write) rather than faking a heuristic that
would either spam false positives or silently miss real decisions.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import dispatch  # noqa: E402
import ledger as ledger_mod  # noqa: E402


def load_seen(state_dir):
    path = os.path.join(state_dir, "notified.json")
    if not os.path.exists(path):
        return {"blocked": [], "done": [], "anomaly": [], "budget_thresholds_hit": []}
    with open(path) as f:
        return json.load(f)


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
