#!/usr/bin/env python3
"""One Command Center orchestrator cycle: ingest -> reconcile -> dispatch ->
dashboard -> interrupt -> persist.

Deliberately a deterministic script, not a `claude -p` invocation, for the
routine mechanical work (frontmatter parsing, guardrail classification,
HTML rendering, bus sends) — a checkable failure mode belongs in a script,
not in a model's judgment. This keeps every cycle cheap (no tokens) and its
behavior fully auditable from the ledger. The NARRATIVE layer (briefing.json)
is the deliberate exception: it's AI-authored at project checkpoints by a
session with real context, and this script only *renders* it (with a visible
staleness stamp), never generates it.

v2: all generated state can live under a STATE ROOT — a dedicated git repo
(local or remote) separate from your KB checkout, so nothing is local-only
and a dead host can be reinstated from a fresh clone of it. run-loop.sh
pulls/pushes that repo around each cycle; this script only reads/writes
files. Also new in v2: the daily digest is actually wired (it was
configurable via policy.json's `digest` block but nothing sent it in v1),
HALT works from the state repo too (= a remote kill switch via a git push
from anywhere, including the GitHub web editor), and an index page across
all instances is regenerated each cycle.

Usage:
    python3 cycle.py --instance <path/to/instance.json> [--dry-run] [--session <id>]
"""
import argparse
import glob
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


def resolve_paths(instance_config, kb_root):
    """Path resolution, two generations of config:
    - v2: `state_root` (e.g. "~/command-center-state") — state/dashboard/briefing
      derived as <state_root>/<name>/{state,dashboard/index.html,briefing.json}.
    - v1 fallback: explicit `state_dir`/`ledger_file`/`dashboard.output` keys,
      resolved relative to kb_root. Kept so existing instance.json files that
      predate `state_root` don't break."""
    name = instance_config["name"]
    if instance_config.get("state_root"):
        root = os.path.expanduser(instance_config["state_root"])
        inst = os.path.join(root, name)
        return {
            "state_root": root,
            "instance_state_dir": os.path.join(inst, "state"),
            "ledger": os.path.join(inst, "state", "orchestrator-log.jsonl"),
            "dashboard_out": os.path.join(inst, "dashboard", "index.html"),
            "briefing": os.path.join(inst, "briefing.json"),
            "halt_candidates": [os.path.join(inst, "HALT"), os.path.join(root, "HALT")],
            "index_out": os.path.join(root, "index.html"),
        }

    def _abs(p):
        p = os.path.expanduser(p)
        return p if os.path.isabs(p) else os.path.join(kb_root, p)

    state_dir = _abs(instance_config["state_dir"])
    return {
        "state_root": None,
        "instance_state_dir": state_dir,
        "ledger": _abs(instance_config["ledger_file"]),
        "dashboard_out": _abs(instance_config["dashboard"]["output"]),
        "briefing": os.path.join(os.path.dirname(state_dir), "briefing.json"),
        "halt_candidates": [os.path.join(os.path.dirname(state_dir), "HALT")],
        "index_out": None,
    }


def discover_instances(kb_root):
    """Every project with a command center — for the index page."""
    out = []
    for path in sorted(glob.glob(os.path.join(kb_root, "projects", "*", "command-center", "instance.json"))):
        try:
            with open(path) as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        paths = resolve_paths(cfg, kb_root)
        out.append({
            "name": cfg["name"],
            "description": cfg.get("description", ""),
            "workers": len(cfg.get("tracked_workers", [])),
            "briefing": dashboard.load_briefing(paths["briefing"]),
        })
    return out


def maybe_send_digest(state, seen, ledger_path, policy, fleet_bus_py, session, dry_run):
    """Send the daily digest if a configured time has passed and none was sent
    today. Tracked in the same notified.json as interrupt dedup."""
    digest_cfg = policy.get("digest") or {}
    if not digest_cfg.get("enabled"):
        return None
    now = time.gmtime()
    today = time.strftime("%Y-%m-%d", now)
    hhmm_now = time.strftime("%H:%M", now)
    sent_key = f"digest:{today}"
    already = sent_key in seen.setdefault("budget_thresholds_hit", [])
    due = any(hhmm_now >= t for t in digest_cfg.get("times_utc", []))
    if already or not due:
        return None
    seen["budget_thresholds_hit"].append(sent_key)
    body = interrupt.format_digest(state, ledger_path, policy)
    import dispatch  # noqa: E402  (lazy: avoids import cost on halted cycles)
    cls, out, reason = dispatch.bus_nudge(
        fleet_bus_py, to="human", body=body, session=session,
        policy=policy, to_human=True, dry_run=dry_run,
    )
    return {"condition": "digest", "message": body, "classification": cls, "result": reason}


def run_cycle(instance_path, *, dry_run=False, session="command-center-orchestrator", kb_root=None):
    kb_root = kb_root or KB_ROOT_DEFAULT
    instance_path = os.path.expanduser(instance_path)
    with open(instance_path) as f:
        instance_config = json.load(f)

    paths = resolve_paths(instance_config, kb_root)
    # v1 configs may also drop HALT next to instance.json in the KB — keep honoring it.
    paths["halt_candidates"].append(os.path.join(os.path.dirname(os.path.abspath(instance_path)), "HALT"))

    policy = guardrail.load_policy(os.path.join(ENGINE_DIR, "policy.json"))
    briefing = dashboard.load_briefing(paths["briefing"])
    result = {"instance": instance_config["name"], "halted": False}

    halt_path = next((p for p in paths["halt_candidates"] if os.path.exists(p)), None)
    if halt_path:
        result["halted"] = True
        result["message"] = f"HALT file present at {halt_path} — dispatch skipped, ingest/dashboard still ran"
        ledger_mod.append(paths["ledger"], {"event": "halt_observed", "halt_path": halt_path})
        state = reconcile.build_state(kb_root, instance_config)
        state["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cycles_today = ledger_mod.cycles_today(paths["ledger"])
        dashboard.write(state, briefing, f"{cycles_today} cycles today · HALTED — dispatch paused", paths["dashboard_out"])
        result["state"] = state
        return result

    os.makedirs(paths["instance_state_dir"], exist_ok=True)

    # 1. Ingest + 2. Reconcile
    state = reconcile.build_state(kb_root, instance_config)
    state["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ledger_mod.append(paths["ledger"], {
        "event": "reconcile",
        "in_flight": len(state["triggers_in_flight"]),
        "blocked": len(state["triggers_blocked"]),
        "done": len(state["triggers_done"]),
        "live_sessions": len(state["sessions_live"]),
        "anomalies": len([s for s in state["sessions_stale_or_dead"] if s.get("claim")]),
    })

    # 3. Dispatch — v1 has no autonomous NEW-trigger creation; mechanism proven in dispatch.py.
    ledger_mod.append(paths["ledger"], {"event": "dispatch", "actions_taken": 0, "note": "no new work identified this cycle"})

    # 4. Dashboard (+ fleet-wide index when a state_root exists)
    cycles_today = ledger_mod.cycles_today(paths["ledger"])
    budget_pct = ledger_mod.budget_pct_today(paths["ledger"], policy["budget"]["max_cycles_per_day"])
    dashboard.write(state, briefing, f"{cycles_today} cycles today · budget {budget_pct}%", paths["dashboard_out"])
    if paths["index_out"]:
        dashboard.write_index(discover_instances(kb_root), paths["index_out"])

    # 5. Interrupt-check + daily digest
    seen = interrupt.load_seen(paths["instance_state_dir"])
    events = interrupt.evaluate(state, seen, paths["ledger"], policy)
    fleet_bus_py = find_fleet_bus_py(kb_root)
    sent = interrupt.send_all(events, fleet_bus_py, session, policy, dry_run=dry_run) if events else []
    digest = maybe_send_digest(state, seen, paths["ledger"], policy, fleet_bus_py, session, dry_run)
    if digest:
        sent.append(digest)
    interrupt.save_seen(paths["instance_state_dir"], seen)
    for s in sent:
        ledger_mod.append(paths["ledger"], {"event": "interrupt_sent", **s})

    result["state"] = state
    result["interrupts_fired"] = sent
    result["budget_pct"] = budget_pct

    # 6. Persist
    ledger_mod.append(paths["ledger"], {"event": "cycle_complete", "budget_pct": budget_pct})
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
