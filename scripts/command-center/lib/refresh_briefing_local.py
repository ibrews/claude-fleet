#!/usr/bin/env python3
"""refresh_briefing_local.py — cheap-LLM narrative refresh for the Command
Center briefing, per the graduated dispatch lane already in fleet/dispatch.md:
"KB writing / daily logs -> llama3.1:8b on Alpha, ask-first, draft then you edit."

Scope is deliberately narrow: this ONLY drafts `one_liner_now` and
`human_action_queue.items` — never north_star, phases, recommendations, or
problems (those stay human/Claude-authored at real checkpoints, per
briefing.json's own `_authorship` field). It exists so the mechanical
bookkeeping drift (a trigger flipped from in_flight to done, nothing else
changed) doesn't require a Claude session just to update two narrative
strings.

Two paths, per the trigger spec:
  1. PURE BOOKKEEPING diff (only trigger status flips since briefing.updated_at,
     no new findings/decisions) -> draft with the local model, auto-commit +
     push the state-root repo directly. Zero Claude tokens.
  2. SUBSTANTIVE diff (a root-cause claim, a risk flag, anything that isn't
     pure status bookkeeping) -> draft the same way but leave it as an
     uncommitted local diff to briefing.json, flagged for a Claude/human
     review pass before commit (the "ask-first" half of the lane).

Classification is a conservative, deterministic keyword heuristic over the
ledger's own text fields (dispatch notes, interrupt messages) — NOT the LLM's
call. This matches guardrail.py's existing house style in this same directory
("unknown action types fail closed, not open"): if the heuristic can't
positively confirm the diff is pure bookkeeping, it defaults to substantive
(safer path), never the other way around.

*** KNOWN RISK — READ BEFORE ENABLING THE AUTO-COMMIT PATH UNATTENDED ***
fleet/dispatch.md's own NIM eval table says, verbatim: "Do not use for KB
writing unattended: llama3.1:8b on Alpha — hallucinated 'Neural Instructions
Machine', fabricated endpoints (eval 3/10)." That eval is about free-prose KB
writing; this script only asks for two constrained JSON fields and validates
the response structurally before ever auto-committing (see
`_validate_draft()`) — but structural validation catches malformed JSON, not
confidently-wrong PROSE (a plausible-sounding but fabricated one-liner would
pass validation). Given that documented eval, treat the "bookkeeping ->
auto-commit" path as unproven until it has its own eval-gallery run; until
then this is the one honest gap in an otherwise-tested deliverable. See this
script's test harness output for what WAS actually exercised.

Usage:
    python3 refresh_briefing_local.py --instance-dir <path/to/state_root/<name>> \\
        [--ollama-url http://localhost:11434/api/generate] [--model llama3.1:8b] \\
        [--min-changes 3] [--min-hours 2] [--dry-run] [--no-push] [--force]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
# ^ Matches fleet/dispatch.md's "Quick write / classify -> llama3.1:8b on Alpha
# (local)" curl convention verbatim. This script is designed to be wired into
# cycle.py's ALREADY-ALWAYS-ON loop on Alpha (per the trigger spec, point 2),
# where "localhost" is correct because the script runs ON Alpha. Override
# --ollama-url when testing from elsewhere (e.g. this repo's test harness
# SSHes the script over to Alpha rather than trying to reach 11434 through
# Tailscale, which Alpha's Ollama is not currently bound to — see test notes).
DEFAULT_MODEL = "llama3.1:8b"

# Deterministic "is this substantive" heuristic. Deliberately over-inclusive:
# false positives just mean an extra human-reviewed draft instead of an
# auto-commit, which is the safe direction to be wrong in.
SUBSTANTIVE_KEYWORDS = [
    "root-caus", "root caus", "rootcaus", "blocker", "risk", "regression",
    "disprov", "diagnos", "decision", "finding", "broke", "crash", "critical",
    "unblock", "hypothesis", "anomaly", "failed", "failure", "incident",
    "security", "data loss", "rollback",
]


def _log(msg):
    print(f"[refresh_briefing_local] {msg}", file=sys.stderr)


def read_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def read_ledger_since(ledger_path, since_iso):
    """All ledger events with ts_iso > since_iso (string compare is safe: both
    are ISO-8601 UTC 'Z' timestamps, same format ledger.py always writes)."""
    events = []
    if not ledger_path or not os.path.exists(ledger_path):
        return events
    with open(ledger_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not since_iso or e.get("ts_iso", "") > since_iso:
                events.append(e)
    return events


def _event_text(e):
    """Every free-text field an event might carry, concatenated for keyword scan."""
    parts = []
    for k in ("note", "task", "task_title", "message", "reason", "action"):
        v = e.get(k)
        if v:
            parts.append(str(v))
    return " ".join(parts).lower()


def classify_diff(events):
    """Returns (classification, reason). classification in {"bookkeeping","substantive","empty"}."""
    if not events:
        return "empty", "no ledger events since last briefing update"

    hits = []
    for e in events:
        text = _event_text(e)
        for kw in SUBSTANTIVE_KEYWORDS:
            if kw in text:
                hits.append((kw, e.get("event"), text[:120]))
                break

    if hits:
        return "substantive", f"{len(hits)} event(s) matched substantive keywords, e.g. {hits[0][0]!r} in a {hits[0][1]!r} event"

    # No keyword hits — but only call it "bookkeeping" if the events are
    # themselves the mechanical kinds we expect (reconcile/dispatch/
    # cycle_complete/interrupt_sent with a digest condition). Anything else
    # unrecognized fails closed to substantive, per this directory's existing
    # "unknown -> fail closed" convention (guardrail.py).
    mechanical_types = {"reconcile", "cycle_complete", "dispatch", "halt_observed"}
    unknown = [e for e in events if e.get("event") not in mechanical_types
               and not (e.get("event") == "interrupt_sent" and e.get("condition") == "digest")]
    if unknown:
        kinds = sorted({e.get("event") for e in unknown})
        return "substantive", f"{len(unknown)} event(s) of non-mechanical type(s) {kinds} — failing closed to substantive"

    return "bookkeeping", f"{len(events)} mechanical event(s), no substantive keywords, no unrecognized event types"


def _reconcile_trigger_delta(events):
    """Proxy for 'how many trigger status flips' — sum of |delta| across
    in_flight/blocked/done counts between the first and last reconcile event
    in the window. Cheap, uses data the ledger already carries every cycle."""
    reconciles = [e for e in events if e.get("event") == "reconcile"]
    if len(reconciles) < 2:
        return len(reconciles)  # 0 or 1 reconcile: nothing to diff yet
    first, last = reconciles[0], reconciles[-1]
    delta = 0
    for k in ("in_flight", "blocked", "done"):
        delta += abs(last.get(k, 0) - first.get(k, 0))
    return delta


def gating_ok(events, briefing, min_changes=3, min_hours=2, force=False):
    """Only fire when there's been enough drift, so this doesn't spam-call the
    model every ~30min cycle (per the trigger spec)."""
    if force:
        return True, "forced"
    delta = _reconcile_trigger_delta(events)
    if delta >= min_changes:
        return True, f"{delta} trigger-count changes >= min_changes={min_changes}"

    updated_at = (briefing or {}).get("updated_at")
    if updated_at:
        try:
            t = time.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ")
            age_hours = (time.time() - time.mktime(t) + time.timezone) / 3600.0
            if age_hours >= min_hours:
                return True, f"briefing is {age_hours:.1f}h old >= min_hours={min_hours}"
        except ValueError:
            pass
    return False, f"only {delta} trigger-count changes and briefing is recent — not enough drift yet"


def build_prompt(briefing, events, classification):
    b = briefing or {}
    haq = (b.get("human_action_queue") or {}).get("items") or []
    summary_lines = []
    for e in events[-25:]:  # cap context — this model has no need for the full history
        kind = e.get("event")
        if kind == "reconcile":
            summary_lines.append(
                f"- reconcile: in_flight={e.get('in_flight')} blocked={e.get('blocked')} "
                f"done={e.get('done')} live_sessions={e.get('live_sessions')}"
            )
        elif kind == "dispatch":
            summary_lines.append(f"- dispatch: {e.get('task') or e.get('note') or e.get('action')}")
        elif kind == "cycle_complete":
            continue  # no narrative content
        else:
            summary_lines.append(f"- {kind}: {_event_text(e)[:160]}")
    ledger_summary = "\n".join(summary_lines) or "(no notable events)"

    haq_summary = "\n".join(
        f"  #{it.get('rank')} {it.get('title')} — {it.get('status')}" for it in haq
    ) or "  (none)"

    return f"""You are drafting TWO fields of a JSON status briefing for a live engineering
project. This is a {classification} update — bookkeeping only if the ledger below shows no new
findings, just status-count changes.

Current one_liner_now:
{b.get("one_liner_now", "(none yet)")}

Current human_action_queue items:
{haq_summary}

Ledger events since the last briefing update:
{ledger_summary}

Write updated values for ONLY these two fields, reflecting what actually changed above. Do not
invent facts, file paths, root causes, or names not present in the ledger events. If nothing
material changed, keep the text close to the current value.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{"one_liner_now": "<one or two sentences>", "human_action_queue_items": [{{"rank": 1, "title": "...", "status": "...", "why": "..."}}]}}
"""


def call_ollama(url, model, prompt, timeout=120):
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",  # Ollama structured-output mode — reduces (does not eliminate) free-prose drift
        "options": {"num_predict": 800},
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"ollama request failed: {e}"
    except json.JSONDecodeError as e:
        return None, f"ollama returned non-JSON envelope: {e}"

    raw = body.get("response", "")
    try:
        draft = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"model response was not valid JSON ({e}): {raw[:200]!r}"
    return draft, None


def _validate_draft(draft):
    """Structural validation only (see module docstring's KNOWN RISK note —
    this cannot catch confidently-wrong prose, only malformed shape)."""
    if not isinstance(draft, dict):
        return False, "draft is not a JSON object"
    one_liner = draft.get("one_liner_now")
    items = draft.get("human_action_queue_items")
    if not isinstance(one_liner, str) or not (10 <= len(one_liner) <= 2000):
        return False, "one_liner_now missing or an implausible length"
    if not isinstance(items, list):
        return False, "human_action_queue_items missing or not a list"
    for it in items:
        if not isinstance(it, dict) or "title" not in it or "status" not in it:
            return False, f"malformed human_action_queue item: {it!r}"
    return True, "ok"


def apply_draft(briefing, draft):
    """Returns a new briefing dict with ONLY one_liner_now + human_action_queue.items
    replaced — everything else (north_star, phases, recommendations, problems,
    links, checkpoints, updated_by) is preserved untouched."""
    out = dict(briefing or {})
    out["one_liner_now"] = draft["one_liner_now"]
    haq = dict(out.get("human_action_queue") or {})
    haq["items"] = draft["human_action_queue_items"]
    out["human_action_queue"] = haq
    out["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out["updated_by"] = f"refresh_briefing_local.py ({DEFAULT_MODEL} on Alpha) — mechanical narrative refresh"
    return out


def git_commit_push(repo_dir, rel_path, message, push=True):
    subprocess.run(["git", "-C", repo_dir, "add", rel_path], check=True)
    diff = subprocess.run(["git", "-C", repo_dir, "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return False, "nothing to commit (draft identical to committed state)"
    subprocess.run(["git", "-C", repo_dir, "commit", "-q", "-m", message], check=True)
    if push:
        subprocess.run(["git", "-C", repo_dir, "push", "-q"], check=True)
    return True, "committed" + (" + pushed" if push else " (push skipped: --no-push)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance-dir", required=True, help="e.g. ~/command-center-state/your-project")
    ap.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--min-changes", type=int, default=3)
    ap.add_argument("--min-hours", type=float, default=2)
    ap.add_argument("--force", action="store_true", help="skip the drift gate")
    ap.add_argument("--dry-run", action="store_true", help="draft + classify, never write or commit")
    ap.add_argument("--no-push", action="store_true", help="commit locally but don't push (bookkeeping path only)")
    args = ap.parse_args()

    instance_dir = os.path.expanduser(args.instance_dir)
    briefing_path = os.path.join(instance_dir, "briefing.json")
    ledger_path = os.path.join(instance_dir, "state", "orchestrator-log.jsonl")
    repo_dir = instance_dir
    while repo_dir != "/" and not os.path.isdir(os.path.join(repo_dir, ".git")):
        repo_dir = os.path.dirname(repo_dir)
    if repo_dir == "/":
        repo_dir = instance_dir  # no repo found — commit step will just fail loudly later

    briefing = read_json(briefing_path, {})
    events = read_ledger_since(ledger_path, (briefing or {}).get("updated_at"))

    ok, gate_reason = gating_ok(events, briefing, args.min_changes, args.min_hours, args.force)
    result = {"gate": {"fired": ok, "reason": gate_reason}}
    if not ok:
        print(json.dumps(result, indent=2))
        return 0

    classification, class_reason = classify_diff(events)
    result["classification"] = {"kind": classification, "reason": class_reason}
    if classification == "empty":
        print(json.dumps(result, indent=2))
        return 0

    prompt = build_prompt(briefing, events, classification)
    draft, err = call_ollama(args.ollama_url, args.model, prompt)
    if err:
        result["error"] = err
        print(json.dumps(result, indent=2))
        return 1

    valid, why = _validate_draft(draft)
    result["validation"] = {"ok": valid, "reason": why}
    if not valid:
        print(json.dumps(result, indent=2))
        return 1

    new_briefing = apply_draft(briefing, draft)
    result["draft"] = {"one_liner_now": draft["one_liner_now"],
                        "human_action_queue_items": len(draft["human_action_queue_items"])}

    if args.dry_run:
        result["action"] = "dry-run — not written"
        print(json.dumps(result, indent=2))
        return 0

    with open(briefing_path, "w") as f:
        json.dump(new_briefing, f, indent=2)
        f.write("\n")

    if classification == "bookkeeping":
        rel = os.path.relpath(briefing_path, repo_dir)
        committed, msg = git_commit_push(
            repo_dir, rel,
            f"briefing: mechanical narrative refresh ({args.model}, bookkeeping-only)",
            push=not args.no_push,
        )
        result["action"] = msg if committed else msg
    else:
        result["action"] = "written to briefing.json as an UNCOMMITTED local diff — needs Claude/human review before commit (substantive change)"

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
