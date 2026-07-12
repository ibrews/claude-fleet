#!/usr/bin/env python3
"""Append-only ledger for the Command Center orchestrator.

Every dispatch, interrupt decision, spawn, and budget tick appends one JSON
line here — never rewritten, never truncated by the orchestrator itself.
This is the audit trail the dashboard reads and the thing you'd point to
if you ever needed to answer "wait, why did it do that."

Budget accounting note (honest limitation): true token-spend metering
requires wiring into Claude Code's own usage stats (~/.claude/usage-state.json
per departments/engineering/hooks/usage-budget-check.sh), which is
machine-local and not something this stdlib script should assume exists on
A machine-local budget-tracking hook. v1 tracks CYCLE COUNT against max_cycles_per_day as the budget proxy
(a hard, always-available number) and leaves real token-based budget wiring
as an explicit next step — not silently faked as equivalent.
"""
import json
import os
import time


def append(ledger_path, event):
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    event = dict(event)
    event.setdefault("ts_epoch", int(time.time()))
    event.setdefault("ts_iso", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with open(ledger_path, "a") as f:
        f.write(json.dumps(event) + "\n")


def read_all(ledger_path):
    if not os.path.exists(ledger_path):
        return []
    out = []
    with open(ledger_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # tolerate a partially-written last line, never crash the loop on it
    return out


def cycles_today(ledger_path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return sum(
        1 for e in read_all(ledger_path)
        if e.get("event") == "cycle_complete" and e.get("ts_iso", "").startswith(today)
    )


def budget_pct_today(ledger_path, max_cycles_per_day):
    if max_cycles_per_day <= 0:
        return 0
    return round(100.0 * cycles_today(ledger_path) / max_cycles_per_day, 1)


if __name__ == "__main__":
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "orchestrator-log.jsonl")
        append(path, {"event": "cycle_complete", "cycle": 1})
        append(path, {"event": "dispatch", "action": "dispatch_trigger", "trigger": "test-trigger"})
        append(path, {"event": "cycle_complete", "cycle": 2})
        events = read_all(path)
        assert len(events) == 3, events
        pct = budget_pct_today(path, max_cycles_per_day=48)
        print(f"self-test ok: {len(events)} events, {cycles_today(path)} cycles today, budget {pct}%")
