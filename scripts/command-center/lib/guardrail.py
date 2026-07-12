#!/usr/bin/env python3
"""Guardrail classifier for the Command Center orchestrator.

Classifies a proposed action against policy.json's green/yellow/red lists.
spawn_worker is special-cased: it is only green while under both the
concurrency cap and the budget warn threshold; otherwise it is reclassified
to the red action spawn_beyond_cap / exceed_budget. This is the one place
that logic lives — dispatch.py must call classify(), never inspect
policy.json's lists directly, so the cap math can't drift out of sync.
"""
import json
import os

GREEN, YELLOW, RED = "green", "yellow", "red"


def load_policy(policy_path):
    with open(policy_path) as f:
        return json.load(f)


def classify(action_type, policy, *, current_workers=0, budget_pct=0):
    """Returns (classification, reason)."""
    classes = policy["action_classes"]
    budget = policy["budget"]

    if action_type == "spawn_worker":
        if current_workers >= budget["max_concurrent_workers"]:
            return RED, (
                f"spawn_beyond_cap: {current_workers} workers already running, "
                f"cap is {budget['max_concurrent_workers']}"
            )
        if budget_pct >= budget["stop_threshold_pct"]:
            return RED, f"exceed_budget: at {budget_pct}%, stop threshold is {budget['stop_threshold_pct']}%"
        if budget_pct >= budget["warn_threshold_pct"]:
            return YELLOW, (
                f"spawn allowed but budget at {budget_pct}% "
                f"(warn threshold {budget['warn_threshold_pct']}%) — notify same cycle"
            )
        return GREEN, f"spawn ok: {current_workers}/{budget['max_concurrent_workers']} workers, budget {budget_pct}%"

    if action_type in classes.get("green", []):
        return GREEN, "listed green in policy.json"
    if action_type in classes.get("yellow", []):
        return YELLOW, "listed yellow in policy.json — act, then notify same cycle"
    if action_type in classes.get("red", []):
        return RED, "listed red in policy.json — never autonomous, ping + wait"

    # Unknown action types fail closed, not open.
    return RED, f"unknown action_type '{action_type}' not in any policy list — failing closed"


def halt_active(instance_dir, policy):
    return os.path.exists(os.path.join(instance_dir, policy.get("halt_file", "HALT")))


if __name__ == "__main__":
    import sys

    policy = load_policy(os.path.join(os.path.dirname(__file__), "..", "policy.json"))
    tests = [
        ("dispatch_trigger", {}),
        ("push_shared_or_main", {}),
        ("spawn_worker", {"current_workers": 1, "budget_pct": 10}),
        ("spawn_worker", {"current_workers": 3, "budget_pct": 10}),
        ("spawn_worker", {"current_workers": 1, "budget_pct": 92}),
        ("frobnicate_unknown", {}),
    ]
    for action, kwargs in tests:
        cls, reason = classify(action, policy, **kwargs)
        print(f"{action:28s} -> {cls:6s} ({reason})")
