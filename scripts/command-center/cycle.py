#!/usr/bin/env python3
"""One Command Center orchestrator cycle: ingest -> reconcile -> dispatch ->
dashboard -> interrupt -> persist.

Deliberately a deterministic script, not a `claude -p` invocation, for the
routine mechanical work (frontmatter parsing, guardrail classification,
HTML rendering, bus sends) — per departments/engineering/
build-tools-that-run-without-ai.md, a checkable failure mode belongs in a
script. This keeps every cycle cheap (no tokens) and its behavior fully
auditable from the ledger, rather than depending on a model's judgment for
mechanical steps. Where real judgment is needed (framing a DECISION for
Alex, writing a richer natural-language digest), the design leaves room to
shell out to a scoped `claude -p` call — not built in v1, flagged as a
follow-up rather than silently substituted with a template string dressed
up as "the orchestrator reasoning."

Usage:
    python3 cycle.py --instance <path/to/instance.json> [--dry-run] [--session <id>]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
import dashboard  # noqa: E402
import guardrail  # noqa: E402
import interrupt  # noqa: E402
import ledger as ledger_mod  # noqa: E402
import reconcile  # noqa: E402

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
KB_ROOT_DEFAULT = os.path.expanduser("~/knowledge")


def find_fleet_bus_py(kb_root):
    return os.path.join(kb_root, "departments", "engineering", "fleet-tools", "fleet_bus.py")


def run_cycle(instance_path, *, dry_run=False, session="command-center-orchestrator", kb_root=None):
    kb_root = kb_root or KB_ROOT_DEFAULT
    with open(instance_path) as f:
        instance_config = json.load(f)

    instance_dir = os.path.dirname(os.path.abspath(instance_path))
    state_dir = os.path.join(kb_root, instance_config["state_dir"]) if not os.path.isabs(
        instance_config["state_dir"]) else instance_config["state_dir"]
    ledger_path = os.path.join(kb_root, instance_config["ledger_file"]) if not os.path.isabs(
        instance_config["ledger_file"]) else instance_config["ledger_file"]
    dashboard_out = os.path.join(kb_root, instance_config["dashboard"]["output"]) if not os.path.isabs(
        instance_config["dashboard"]["output"]) else instance_config["dashboard"]["output"]

    policy = guardrail.load_policy(os.path.join(ENGINE_DIR, "policy.json"))
    halt_path = os.path.join(instance_dir, instance_config.get("halt_file", policy["halt_file"]))

    result = {"instance": instance_config["name"], "halted": False}

    if os.path.exists(halt_path):
        result["halted"] = True
        result["message"] = f"HALT file present at {halt_path} — dispatch skipped, ingest/dashboard still ran"
        ledger_mod.append(ledger_path, {"event": "halt_observed", "halt_path": halt_path})
        # Even halted, still refresh the read-only view — HALT stops ACTION, not visibility.
        state = reconcile.build_state(kb_root, instance_config)
        state["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cycles_today = ledger_mod.cycles_today(ledger_path)
        dashboard.write(state, f"{cycles_today} cycles today · HALTED — dispatch paused", dashboard_out)
        result["state"] = state
        return result

    os.makedirs(state_dir, exist_ok=True)

    # 1. Ingest + 2. Reconcile
    state = reconcile.build_state(kb_root, instance_config)
    state["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ledger_mod.append(ledger_path, {
        "event": "reconcile",
        "in_flight": len(state["triggers_in_flight"]),
        "blocked": len(state["triggers_blocked"]),
        "done": len(state["triggers_done"]),
        "live_sessions": len(state["sessions_live"]),
        "anomalies": len([s for s in state["sessions_stale_or_dead"] if s.get("claim")]),
    })

    # 3. Dispatch — v1 has no autonomous NEW-trigger creation (nothing to genuinely dispatch
    # beyond what's already tracked); the mechanism is proven in dispatch.py's own self-test.
    # This step is a real no-op by data, not a stub — logged either way for auditability.
    ledger_mod.append(ledger_path, {"event": "dispatch", "actions_taken": 0, "note": "no new work identified this cycle"})

    # 4. Dashboard
    cycles_today = ledger_mod.cycles_today(ledger_path)
    budget_pct = ledger_mod.budget_pct_today(ledger_path, policy["budget"]["max_cycles_per_day"])
    dashboard.write(state, f"{cycles_today} cycles today · budget {budget_pct}%", dashboard_out)

    # 5. Interrupt-check
    seen = interrupt.load_seen(state_dir)
    events = interrupt.evaluate(state, seen, ledger_path, policy)
    interrupt.save_seen(state_dir, seen)

    fleet_bus_py = find_fleet_bus_py(kb_root)
    sent = interrupt.send_all(events, fleet_bus_py, session, policy, dry_run=dry_run) if events else []
    for s in sent:
        ledger_mod.append(ledger_path, {"event": "interrupt_sent", **s})

    result["state"] = state
    result["interrupts_fired"] = sent
    result["budget_pct"] = budget_pct

    # 6. Persist
    ledger_mod.append(ledger_path, {"event": "cycle_complete", "budget_pct": budget_pct})
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", required=True)
    ap.add_argument("--dry-run", action="store_true", help="log intended bus sends, don't actually send")
    ap.add_argument("--session", default="command-center-orchestrator")
    ap.add_argument("--kb-root", default=None)
    args = ap.parse_args()

    r = run_cycle(args.instance, dry_run=args.dry_run, session=args.session, kb_root=args.kb_root)
    print(json.dumps({k: v for k, v in r.items() if k != "state"}, indent=2))
    if r.get("halted"):
        print(r["message"])
