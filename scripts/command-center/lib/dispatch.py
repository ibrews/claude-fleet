#!/usr/bin/env python3
"""Dispatch actions for the Command Center orchestrator.

Every function here calls guardrail.classify() BEFORE doing anything, and
every attempt (allowed or refused) gets logged by the caller (cycle.py) to
the ledger. Nothing in this file bypasses guardrail.py — that is the one
enforcement point, deliberately kept singular so it can't drift.

spawn_worker is intentionally NOT wired to actually launch a process yet.
Actually invoking `claude -p` headless against a live project repo is a
real side effect with real budget/resource cost — the design calls for
"auto-spawn within cap" as the target autonomy level, but landing that
silently inside a scaffolding dry-run would be exactly the kind of
unrequested consequential action the standing safety rules ask to be
surfaced first. v1 logs the guardrail-gated decision (would spawn / would
refuse, and why) so the cap math is provable; wiring the real subprocess
launch is a flagged next step, not silently done.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
import guardrail  # noqa: E402
import prior_art  # noqa: E402

TRIGGER_TEMPLATE = """---
id: {id}
created: {created}
source: command-center-orchestrator
target: {target}
priority: {priority}
status: {status}
claimed_by:
claimed_pid:
claimed_at:
completed_at:
inbox_file:
inbox_line:
prior_art: "{prior_art}"
title: "{title}"
updated: {created_date}
tags: [trigger, command-center, {instance}]
---
> Created by the {instance} Command Center orchestrator (autonomous, green-classified action).
> Prior-art check: {prior_art}
> Claim before you start: `~/knowledge/scripts/inbox-claim.sh {id}.md`

## Task

{task}

## Done criteria

{done_criteria}

## Result

<!-- Filled in by executing machine when complete. -->
"""


def create_trigger(triggers_dir, *, trigger_id, target, title, task, done_criteria,
                    instance, priority="normal", policy, prior_art_summary="", dry_run=False):
    """Writes a real trigger file matching resources/templates/inbox-action-trigger-template.md.
    Returns (classification, path_or_None, reason). Refuses (never writes) if not green,
    AND refuses (separately) if the task is build-shaped and prior_art_summary is empty —
    the prior-art gate. This is the one place PRIOR-art enforcement can happen for
    orchestrator-authored triggers; the PreToolUse hook (prior-art-gate-check.sh) is the
    backstop for triggers a human or another session writes directly, bypassing this function."""
    check = prior_art.check_trigger_text(title, task, {"prior_art": prior_art_summary})
    if not check["ok"]:
        return "refused_no_prior_art", None, check["reason"]

    cls, reason = guardrail.classify("dispatch_trigger", policy)
    if cls != guardrail.GREEN:
        return cls, None, reason

    import time
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    today = time.strftime("%Y-%m-%d", time.gmtime())
    content = TRIGGER_TEMPLATE.format(
        id=trigger_id, created=now, target=target, priority=priority,
        status="pending", title=title, created_date=today, instance=instance,
        task=task, done_criteria=done_criteria,
        prior_art=prior_art_summary or "n/a — not build-shaped",
    )
    path = os.path.join(triggers_dir, f"{trigger_id}.md")
    if dry_run:
        return cls, path, f"DRY RUN — would write {len(content)} bytes to {path}"
    os.makedirs(triggers_dir, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return cls, path, reason


def bus_nudge(fleet_bus_py, *, to, body, session, policy, to_human=False, dry_run=False):
    """Sends via fleet_bus.py send. --to human is the interrupt-the operator path."""
    cls, reason = guardrail.classify("bus_nudge_worker", policy)
    if cls != guardrail.GREEN:
        return cls, None, reason

    target = "human" if to_human else to
    cmd = ["python3", fleet_bus_py, "send", "--to", target, "--body", body, "--session", session]
    if dry_run:
        return cls, None, f"DRY RUN — would run: {' '.join(cmd)}"
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ok = result.returncode == 0
        return cls, (result.stdout or result.stderr).strip(), (
            "sent" if ok else f"fleet_bus.py exited {result.returncode}: {result.stderr.strip()}"
        )
    except Exception as e:
        return cls, None, f"send failed: {e}"


def decide_spawn(*, current_workers, budget_pct, worker_name, policy):
    """Guardrail-gated decision only — does NOT launch a process. See module docstring."""
    cls, reason = guardrail.classify(
        "spawn_worker", policy, current_workers=current_workers, budget_pct=budget_pct
    )
    verb = {"green": "WOULD SPAWN", "yellow": "WOULD SPAWN (notify)", "red": "REFUSED"}[cls]
    return cls, f"{verb} worker '{worker_name}': {reason}"


if __name__ == "__main__":
    import json
    import tempfile

    policy = guardrail.load_policy(os.path.join(os.path.dirname(__file__), "..", "policy.json"))

    with tempfile.TemporaryDirectory() as tmp:
        cls, path, reason = create_trigger(
            tmp, trigger_id="cc-selftest-2026-07-12", target="none",
            title="Command Center dispatch.py self-test",
            task="No real task — proves create_trigger() writes a template-conformant file.",
            done_criteria="File exists and matches the trigger template shape.",
            instance="selftest", policy=policy,
        )
        print("create_trigger:", cls, path, reason)
        assert cls == guardrail.GREEN and path and os.path.exists(path)
        with open(path) as f:
            body = f.read()
        assert body.startswith("---\nid: cc-selftest-2026-07-12\n")
        assert "status: pending" in body
        print("  -> template shape verified")

    cls, msg = decide_spawn(current_workers=0, budget_pct=4.2, worker_name="groom-conform", policy=policy)
    print("decide_spawn (0/3, 4.2%):", cls, "-", msg)
    cls, msg = decide_spawn(current_workers=3, budget_pct=4.2, worker_name="groom-conform", policy=policy)
    print("decide_spawn (3/3, 4.2%):", cls, "-", msg)

    # Prior-art gate: build-shaped + no summary -> refused, no file written.
    with tempfile.TemporaryDirectory() as tmp:
        cls, path, reason = create_trigger(
            tmp, trigger_id="cc-build-no-priorart", target="beta",
            title="Build a new groom-conform pipeline for MH_Character",
            task="Implement a new per-vertex groom conforming solution from scratch.",
            done_criteria="Grooms conform.", instance="selftest", policy=policy,
        )
        print("create_trigger (build-shaped, no prior_art):", cls, path, reason)
        assert cls == "refused_no_prior_art" and path is None
        assert not os.path.exists(os.path.join(tmp, "cc-build-no-priorart.md"))
        print("  -> correctly refused, no file written")

    # Same build-shaped task WITH a prior_art summary -> proceeds normally.
    with tempfile.TemporaryDirectory() as tmp:
        cls, path, reason = create_trigger(
            tmp, trigger_id="cc-build-with-priorart", target="beta",
            title="Build a new groom-conform pipeline for MH_Character",
            task="Implement a new per-vertex groom conforming solution from scratch.",
            done_criteria="Grooms conform.", instance="selftest", policy=policy,
            prior_art_summary="kb-search 'groom conform' + techniques-graph MetaHuman section — "
                               "live-metahuman-web already solved this, porting its approach, not new.",
        )
        print("create_trigger (build-shaped, WITH prior_art):", cls, path, reason)
        assert cls == guardrail.GREEN and path and os.path.exists(path)
        with open(path) as f:
            assert "prior_art:" in f.read()
        print("  -> correctly proceeded with prior_art recorded in the file")
