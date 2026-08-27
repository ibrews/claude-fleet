#!/usr/bin/env python3
"""Reconcile real KB state into a structured model for one instance.

Reads (does not write, except its own output file) three existing,
untouched fleet primitives:
  - sessions/active/*.md   — presence board (who's doing what, right now)
  - triggers/*.md          — durable work orders
  - inbox/<machine>.md     — durable, human-facing action items

Filters each to an instance's keyword set (from instance.json) and builds
one state model: done / in_flight / blocked / sessions / stale_claims.

Deliberately NO LLM call here — this is mechanical frontmatter parsing.
Per departments/engineering/build-tools-that-run-without-ai.md: a
checkable failure mode (stale claim, dead pid, keyword match) belongs in
a deterministic script, not a model invocation, every cycle.
"""
import glob
import json
import os
import re
import subprocess
import time

import work_items


def parse_frontmatter(path):
    """Compatibility wrapper around the ticket-aware frontmatter parser."""
    return work_items.parse_frontmatter(path)


def matches_keywords(haystack_fields, body, keywords):
    haystack = " ".join(str(v) for v in haystack_fields.values()) + " " + body
    haystack_low = haystack.lower()
    return any(kw.lower() in haystack_low for kw in keywords)


def is_orchestrator_claim(claimed_by):
    """Deterministic check for 'this trigger is claimed by the instance's own
    orchestrator/master session' — a plain substring test on the structured
    claimed_by field (e.g. 'your-project-orchestrator (pensive-hellman-a7a837)'),
    not a fuzzy heuristic over free text. Used to surface subagent-dispatched
    work (which never board-registers a session of its own) as active, per
    the accuracy-bug fix — see command-center-dashboard-accuracy-2026-07-12.md."""
    return "orchestrator" in (claimed_by or "").lower()


def pid_alive(pid_str):
    try:
        pid = int(pid_str)
    except (TypeError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OverflowError):
        return False
    except OSError:
        return False


def collect_sessions(kb_root, keywords, stale_min=15):
    out = []
    now = time.time()
    for path in glob.glob(os.path.join(kb_root, "sessions", "active", "*.md")):
        fields, body = parse_frontmatter(path)
        if not fields:
            continue
        if not matches_keywords(fields, body, keywords):
            continue
        hb_epoch = fields.get("heartbeat_epoch", "")
        try:
            age_min = (now - int(hb_epoch)) / 60.0
        except (TypeError, ValueError):
            age_min = None
        alive = pid_alive(fields.get("pid"))
        out.append({
            "file": os.path.relpath(path, kb_root),
            "machine": fields.get("machine", "?"),
            "slug": fields.get("slug", "?"),
            "doing": fields.get("doing", ""),
            "status": fields.get("status", "?"),
            "claim": fields.get("claim", ""),
            "heartbeat_age_min": round(age_min, 1) if age_min is not None else None,
            "stale": (age_min is not None and age_min > stale_min),
            "pid_alive": alive,
            # "orchestrating" is a reserved status value a project's master/orchestrator
            # session self-sets on the presence board (session-board.sh's `-S` accepts
            # free text; this project's orchestrator deliberately uses this one value
            # to mark itself). A literal field check, not text-sniffing "doing" —
            # deterministic and checkable, per the accuracy-bug fix's requirement.
            "is_master": fields.get("status") == "orchestrating",
        })
    return out


def collect_triggers(kb_root, keywords, project_name=""):
    done, in_flight, blocked = [], [], []
    paths = glob.glob(os.path.join(kb_root, "triggers", "*.md"))
    paths += glob.glob(os.path.join(kb_root, "triggers", "archive", "*.md"))
    for path in paths:
        fields, body = parse_frontmatter(path)
        if not fields:
            continue
        archived = os.path.basename(os.path.dirname(path)) == "archive"
        # Retain only completed v1 evidence after the queue flush. Importing
        # the legacy archive would resurrect years of terminal work into every
        # project matcher and make the cockpit unusable.
        if archived and not (
            fields.get("schema") == work_items.SCHEMA_V1
            and work_items.normalize_status(fields.get("status"), fields.get("schema")) == "completed"
        ):
            continue
        entry = work_items.parse_trigger(path, kb_root)
        project = entry.get("project", "").strip().lower()
        instance_name = str(project_name or (keywords[0] if keywords else "")).strip().lower()
        # New-contract tickets route by explicit project identity. Legacy
        # tickets retain keyword matching until migrated.
        if project:
            if project != instance_name:
                continue
        elif not matches_keywords(fields, body, keywords):
            continue
        # The dashboard/state API should not carry full trigger bodies or a
        # duplicate raw-field map. Both remain available from the linked file.
        entry.pop("body", None)
        entry.pop("fields", None)
        entry.pop("result", None)
        status = entry["status"]
        if status == "completed":
            done.append(entry)
        elif status == "cancelled":
            continue
        elif status == "blocked":
            blocked.append(entry)
        else:
            in_flight.append(entry)
    return done, in_flight, blocked


def collect_inbox_items(kb_root, keywords):
    items = []
    for path in glob.glob(os.path.join(kb_root, "inbox", "*.md")):
        with open(path, errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip().startswith("- ["):
                    continue
                if not any(kw.lower() in line.lower() for kw in keywords):
                    continue
                checked = line.strip().startswith("- [x]")
                items.append({
                    "file": os.path.relpath(path, kb_root),
                    "line": line.strip(),
                    "done": checked,
                })
    return items


def match_tracked_workers(tracked_workers, live_sessions, t_in_flight, t_blocked):
    """Cross-references the instance's named worker roster (instance.json's
    tracked_workers) against live sessions and open triggers, so instance #1's
    first coordinated set is represented explicitly rather than staying
    implicit in the raw keyword-matched lists. Match is a case-insensitive
    substring check of the worker's name/repo against session 'doing' text
    and trigger titles/files — same tolerance level as the keyword filter
    elsewhere in this file, not a stricter guarantee.

    The MASTER/orchestrator session is deliberately excluded from the live-
    session candidates here (found during the accuracy-bug fix's own
    verification, 2026-07-12): its 'doing' text names the umbrella project
    (e.g. "your-project master orchestrator..."), which substring-matches
    ANY tracked worker whose `repo` field equals that same project name —
    a false "live" for work nobody is actually running. The master's own
    liveness is surfaced separately (dashboard's "Live now" panel, starred);
    per-worker "live" status must come from a session actually doing THAT
    worker's task, not the orchestrator merely existing."""
    results = []
    for w in tracked_workers or []:
        needles = [w["name"].lower(), w.get("repo", "").lower()]

        def hits(haystack):
            h = haystack.lower()
            return any(n and n in h for n in needles)

        worker_sessions = [s for s in live_sessions if not s.get("is_master")]
        matched_sessions = [s for s in worker_sessions if hits(s["doing"]) or hits(s.get("machine", ""))]
        matched_blocked = [t for t in t_blocked if hits(t["title"]) or hits(t["file"])]
        matched_in_flight = [t for t in t_in_flight if hits(t["title"]) or hits(t["file"])]

        if matched_sessions:
            status = "live"
        elif matched_blocked:
            status = "blocked"
        elif matched_in_flight:
            status = "trigger open"
        else:
            status = "no current activity"

        results.append({
            "name": w["name"],
            "repo": w.get("repo", ""),
            "note": w.get("note", ""),
            "status": status,
            "matched_sessions": len(matched_sessions),
            "matched_in_flight": len(matched_in_flight),
            "matched_blocked": len(matched_blocked),
        })
    return results


def build_state(kb_root, instance_config):
    keywords = instance_config["keywords"]
    stale_min = instance_config.get("stale_session_minutes", 15)

    sessions = collect_sessions(kb_root, keywords, stale_min)
    t_done, t_in_flight, t_blocked = collect_triggers(
        kb_root, keywords, instance_config.get("name", "")
    )
    inbox_items = collect_inbox_items(kb_root, keywords)

    stale_claims = [s for s in sessions if s["stale"] or not s["pid_alive"]]
    live_sessions = [s for s in sessions if not s["stale"] and s["pid_alive"]]

    # Bug fix (command-center-dashboard-accuracy-2026-07-12): the orchestrator
    # session and any Agent-subagent workers it dispatches never board-register
    # their own sessions/active/*.md entry, so they were invisible to
    # live_sessions even while actively working. The orchestrator's own session
    # IS counted above once it self-tags with an instance keyword (its is_master
    # flag then marks it for the live view). Subagent-dispatched work is
    # reflected here via the trigger it's claimed under — a real, structured
    # field (claimed_by), not a guess — kept SEPARATE from sessions_live (a
    # trigger claim is not proof a process is live right now) so this can never
    # be mistaken for — or silently merged into — the real live-session count.
    orchestrator_dispatched_active = [
        t for t in t_in_flight if is_orchestrator_claim(t.get("claimed_by"))
    ]

    tracked_workers = match_tracked_workers(
        instance_config.get("tracked_workers"), live_sessions, t_in_flight, t_blocked
    )
    all_tickets = t_done + t_in_flight + t_blocked
    ticket_quality = work_items.summarize(all_tickets)
    needs_human = [ticket for ticket in t_in_flight + t_blocked if ticket.get("needs_human")]

    return {
        "instance": instance_config["name"],
        "generated_at": None,  # filled by cycle.py (only place allowed a real timestamp)
        "tracked_workers": tracked_workers,
        "sessions_live": live_sessions,
        "sessions_stale_or_dead": stale_claims,
        "orchestrator_dispatched_active": orchestrator_dispatched_active,
        "triggers_done": t_done,
        "triggers_in_flight": t_in_flight,
        "triggers_blocked": t_blocked,
        "work_item_quality": ticket_quality,
        "needs_human": needs_human,
        "inbox_open": [i for i in inbox_items if not i["done"]],
        "inbox_done": [i for i in inbox_items if i["done"]],
    }


if __name__ == "__main__":
    import sys

    kb_root = os.path.expanduser("~/knowledge")
    instance_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "projects",
        "your-project", "command-center", "instance.json"
    )
    with open(instance_path) as f:
        instance_config = json.load(f)
    state = build_state(kb_root, instance_config)
    print(json.dumps(state, indent=2))
