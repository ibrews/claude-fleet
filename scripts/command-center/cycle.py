#!/usr/bin/env python3
"""One Command Center orchestrator cycle: ingest -> reconcile -> dispatch ->
dashboard -> interrupt -> persist.

Deliberately a deterministic script, not a `claude -p` invocation, for the
routine mechanical work — per departments/engineering/
build-tools-that-run-without-ai.md. The NARRATIVE layer (briefing.json) is
the deliberate exception: it's AI-authored at project checkpoints by a
session with real context, and this script only *renders* it (with a visible
staleness stamp), never generates it.

v2 (2026-07-12): all generated state lives under a STATE ROOT — a dedicated
private git repo (your-org/command-center-state) so nothing is local-only
and a dead machine can be reinstated from a fresh clone. run-loop.sh pulls/
pushes that repo around each cycle; this script only reads/writes files.
Also new in v2: the daily digest is actually wired (it was configured in
policy.json but nothing sent it — found during the v2 review), HALT works
from the state repo too (= remote kill switch via a git push from anywhere),
and an index page across all instances is regenerated each cycle.

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
import phase_sync  # noqa: E402
import reconcile  # noqa: E402
import spawn  # noqa: E402

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
KB_ROOT_DEFAULT = os.path.expanduser("~/knowledge")


def find_fleet_bus_py(kb_root):
    return os.path.join(kb_root, "departments", "engineering", "fleet-tools", "fleet_bus.py")


def resolve_paths(instance_config, kb_root):
    """Path resolution, two generations of config:
    - v2: `state_root` (e.g. "~/command-center-state") — state/dashboard/briefing
      derived as <state_root>/<name>/{state,dashboard/index.html,briefing.json}.
    - v1 fallback: explicit `state_dir`/`ledger_file`/`dashboard.output` keys,
      resolved relative to kb_root. Kept so the public template's existing
      instance.json files don't break."""
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


def run_cycle(instance_path, *, dry_run=False, session="cc-master", kb_root=None):
    # session defaults to "cc-master" (v2): interrupt/digest sends go `--to human`
    # stamped from_session=cc-master, so the operator's Telegram REPLY (tagged #sid=cc-master
    # by the tg-bus bridge) routes back to the live master bus listener instead of
    # falling through to whatever session is attached — the fix for the one-way v1
    # contact surface. Nothing listens as cc-master? The reply falls through exactly
    # as before, so this is safe even before the master session is deployed.
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

    # Keep the phase board + the two progress bigbars in lock-step with the
    # roadmap doc (instance.content_source). A DETERMINISTIC, no-LLM copy of
    # its machine-readable ```phases block into briefing.json — the numbers
    # stay human-authored in the roadmap, this only carries them across so the
    # two can no longer drift (the 2026-07-14 stale-briefing.json fix). Runs
    # before the halt branch so a HALTED cycle still renders fresh phases.
    # Fails safe: on any problem it leaves briefing.json untouched and logs why.
    briefing, phase_sync_result = phase_sync.sync(
        instance_config, kb_root, briefing, paths["briefing"], dry_run=dry_run)
    ledger_mod.append(paths["ledger"], {"event": "phase_sync", **phase_sync_result})
    result["phase_sync"] = phase_sync_result

    halt_path = next((p for p in paths["halt_candidates"] if os.path.exists(p)), None)
    if halt_path:
        result["halted"] = True
        # The kill switch's "terminates spawned children" clause: SIGTERM every
        # live worker before anything else, so a HALT actually stops in-flight
        # spawns, not just future dispatch. Never blocks (best-effort kill).
        killed = spawn.kill_all(paths["instance_state_dir"], paths["ledger"], reason=f"HALT:{halt_path}") \
            if not dry_run else []
        result["workers_killed"] = killed
        result["message"] = (
            f"HALT file present at {halt_path} — dispatch skipped, ingest/dashboard still ran"
            + (f"; killed {len(killed)} live worker(s)" if killed else "")
        )
        ledger_mod.append(paths["ledger"], {"event": "halt_observed", "halt_path": halt_path,
                                            "workers_killed": killed})
        state = reconcile.build_state(kb_root, instance_config)
        state["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state["workers"] = spawn.summarize(paths["instance_state_dir"])
        cycles_today = ledger_mod.cycles_today(paths["ledger"])
        dashboard.write(state, briefing, f"{cycles_today} cycles today · HALTED — dispatch paused", paths["dashboard_out"])
        result["state"] = state
        return result

    os.makedirs(paths["instance_state_dir"], exist_ok=True)

    # 0. Reap spawned workers FIRST — finalize any that exited/overran since last
    #    cycle so the state model (and the cap) reflect reality this cycle.
    reaped = spawn.reap(paths["instance_state_dir"], paths["ledger"], policy)

    # 1. Ingest + 2. Reconcile
    state = reconcile.build_state(kb_root, instance_config)
    state["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Fold spawn state into the model so the dashboard + MCP see live workers,
    # spawnable candidates, and any proposals awaiting the operator's confirmation.
    state["workers"] = spawn.summarize(paths["instance_state_dir"])
    state["spawn_candidates"] = spawn.identify_candidates(state, kb_root)
    state["pending_spawns"] = spawn.load_pending(paths["instance_state_dir"]).get("pending", [])
    # DECISION_NEEDED.md lives next to HALT/briefing.json (instance dir, not state/)
    # — any worker can drop it there when it hits a choice it can't resolve itself.
    # See interrupt.py's module docstring for why this is explicit, not inferred.
    decision_needed_path = os.path.join(os.path.dirname(paths["instance_state_dir"]), "DECISION_NEEDED.md")
    state["decision_needed_file"] = decision_needed_path if os.path.exists(decision_needed_path) else None
    # Deterministic, suggestion-only sanity checks on the phase board (status/pct
    # inconsistencies + staleness). Ephemeral — attached to the per-cycle state
    # model for the dashboard, NEVER written back into briefing.json. The engine
    # surfaces "this pct looks off," a human decides; it never auto-edits a
    # high-stakes progress number.
    state["phase_nudges"] = phase_sync.phase_pct_nudges(
        briefing.get("phases") if briefing else [],
        (briefing or {}).get("phases_updated"),
        len(state["triggers_done"]),
    )
    usage = spawn.read_usage_usd(policy)
    ledger_mod.append(paths["ledger"], {
        "event": "reconcile",
        "in_flight": len(state["triggers_in_flight"]),
        "blocked": len(state["triggers_blocked"]),
        "done": len(state["triggers_done"]),
        "live_sessions": len(state["sessions_live"]),
        "anomalies": len([s for s in state["sessions_stale_or_dead"] if s.get("claim")]),
        "workers_live": state["workers"]["live_count"],
        "workers_reaped": len(reaped),
        "spawn_candidates": len(state["spawn_candidates"]),
        "pending_spawns": len([p for p in state["pending_spawns"] if p.get("status") == "awaiting_confirmation"]),
    })

    # 3. Dispatch — spawn LAUNCH is deliberately NOT autonomous while
    #    policy.spawn.mode == "propose": launches happen only via the Desktop MCP
    #    spawn_worker tool or an the operator-confirmed proposal (confirm_spawn), both of
    #    which call spawn.launch_worker directly. The loop surfaces candidates +
    #    pending proposals (above) but does not launch them here. Flipping mode to
    #    "auto" (the operator's explicit say-so) is what turns this into autonomous launch.
    spawn_mode = (policy.get("spawn") or {}).get("mode", "propose")
    ledger_mod.append(paths["ledger"], {
        "event": "dispatch", "actions_taken": 0, "spawn_mode": spawn_mode,
        "note": f"spawn_mode={spawn_mode}; launches gated to MCP/confirmed proposals this cycle",
    })

    # 4. Dashboard (+ fleet-wide index when a state_root exists)
    cycles_today = ledger_mod.cycles_today(paths["ledger"])
    budget_pct = ledger_mod.budget_pct_today(paths["ledger"], policy["budget"]["max_cycles_per_day"])
    usd_str = ""
    if usage and usage.get("spent_today_usd") is not None:
        usd_str = f" · ${usage['spent_today_usd']:.2f} today"
    live_workers = state["workers"]["live_count"]
    worker_str = f" · {live_workers} live worker(s)" if live_workers else ""
    dashboard.write(state, briefing,
                    f"{cycles_today} cycles today · budget {budget_pct}%{worker_str}{usd_str}",
                    paths["dashboard_out"])
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
    ap.add_argument("--session", default="cc-master",
                    help="sender id for --to human sends; cc-master routes Telegram replies to the master listener")
    ap.add_argument("--kb-root", default=None)
    args = ap.parse_args()

    r = run_cycle(args.instance, dry_run=args.dry_run, session=args.session, kb_root=args.kb_root)
    print(json.dumps({k: v for k, v in r.items() if k != "state"}, indent=2))
    if r.get("halted"):
        print(r["message"])
