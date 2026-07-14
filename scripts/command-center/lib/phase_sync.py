#!/usr/bin/env python3
"""phase_sync.py — DETERMINISTIC (no-LLM) copy of the phase board + progress
bigbars from the roadmap doc into briefing.json.

The problem this fixes (2026-07-14): the your-project dashboard renders its
phase board and its two "to-first-live / full-roadmap" bigbars from
briefing.json, but the *authoritative* per-phase numbers live in the roadmap
doc that people actually edit (instance.json's `content_source`). Those two
drifted apart for a full day, causing real confusion about which file is the
source of truth. This module makes the roadmap doc the single source: it
parses a machine-readable ```phases block out of `content_source` and copies
it verbatim into briefing.json's `phases` + `progress` on every cycle.

Two kinds of number, handled two different ways — both deterministic, no LLM:

  1. Per-phase `pct` — HUMAN-AUTHORED in the roadmap block. Copied verbatim into
     briefing.json's `phases`. No model, no guessing; this step can't hallucinate
     a high-stakes phase number.
  2. The two progress BIGBARS (to-first-show / full-roadmap) — COMPUTED here as
     weighted averages of the phase pcts, so they can never sit stale while the
     phases move underneath them (the failure the operator flagged: 78%/55% unchanged for
     days because they were separately hand-typed). Each phase carries a `weight`
     (its relative size/effort, default 1) and a `first_show` flag (is it on the
     critical path to the Phase-3 "first live show" milestone). to_first_show_pct
     = weighted mean of the first_show phases; full_roadmap_pct = weighted mean of
     ALL phases. Editing any phase pct moves the right bigbar automatically. The
     only human inputs are the per-phase pct/weight/first_show and the note prose
     — never the rolled-up bigbar number itself.

If the block is missing or malformed, briefing.json is left exactly as-is and the
reason is logged; it never fails a cycle.

The block format (a fenced ```phases block containing JSON, stdlib-parseable
with zero third-party deps — PyYAML is intentionally NOT required, since this
runs on Alpha in the run-loop):

    ```phases
    {
      "progress": {"to_first_show_note": "...", "full_roadmap_note": "..."},
      "phases": [
        {"id": "1", "name": "...", "subtitle": "...", "status": "proven",
         "pct": 100, "state": "...", "weight": 1, "first_show": true},
        ...
      ]
    }
    ```

`weight` (default 1 if omitted) and `first_show` (default false) drive the bigbar
computation only — they are NOT copied into briefing.json's phases, which stays
the plain id/name/subtitle/status/pct/state schema the dashboard renders.

Also lifts the roadmap doc's own frontmatter `updated:` date into the briefing
as `phases_updated`, so the dashboard can stamp the phase board with the real
freshness of its source (not the render time, and not the narrative's
updated_at) — the staleness backstop.

Usage (standalone, for testing/debugging a single instance):
    python3 phase_sync.py --instance <path/to/instance.json> [--kb-root ~/knowledge] [--dry-run]
"""
import argparse
import json
import os
import re
import sys

# Every phase MUST carry these — matches briefing.json's phases schema exactly.
# subtitle/state are optional (render as blank) but recommended.
REQUIRED_PHASE_KEYS = ("id", "name", "status", "pct")
VALID_STATUSES = {"proven", "live", "blocked", "planned", "partial"}
# Fields on a briefing.json phase (weight/first_show are compute-only, NOT stored).
DEFAULT_TO_FIRST_SHOW_NOTE = "Weighted average of the phases on the critical path to the first live show."
DEFAULT_FULL_ROADMAP_NOTE = "Weighted average across every phase in the roadmap."

_FENCE_RE = re.compile(r"^```phases[ \t]*\r?\n(.*?)^```", re.MULTILINE | re.DOTALL)


def extract_phases_block(text):
    """Return the raw JSON string inside the first ```phases fenced block, or None."""
    m = _FENCE_RE.search(text or "")
    return m.group(1) if m else None


def frontmatter_updated(text):
    """The roadmap doc's own `updated:` date from its leading YAML frontmatter.
    Returns a 'YYYY-MM-DD' string or None — never invents one. Pure line scan,
    no YAML dependency."""
    if not text or not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        m = re.match(r"\s*updated\s*:\s*['\"]?(\d{4}-\d{2}-\d{2})", line)
        if m:
            return m.group(1)
    return None


def parse_doc(path):
    """Read the content_source doc → (data, updated_date, error).
    data is the parsed block dict ({"phases": [...], "progress": {...}}) or None."""
    if not path or not os.path.exists(path):
        return None, None, f"content_source not found: {path}"
    try:
        with open(path) as f:
            text = f.read()
    except OSError as e:
        return None, None, f"could not read content_source: {e}"

    raw = extract_phases_block(text)
    if raw is None:
        return None, None, "no ```phases block found in content_source"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, frontmatter_updated(text), f"```phases block is not valid JSON: {e}"
    return data, frontmatter_updated(text), None


def validate(data):
    """Structural validation of the parsed block. Returns (ok, reason).
    Conservative: any malformed phase rejects the WHOLE block (fail closed —
    never write a half-synced phase board)."""
    if not isinstance(data, dict):
        return False, "block is not a JSON object"
    phases = data.get("phases")
    if not isinstance(phases, list) or not phases:
        return False, "block has no non-empty 'phases' list"
    for i, p in enumerate(phases):
        if not isinstance(p, dict):
            return False, f"phase #{i} is not an object"
        missing = [k for k in REQUIRED_PHASE_KEYS if k not in p]
        if missing:
            return False, f"phase #{i} ({p.get('id', '?')}) missing keys {missing}"
        if not isinstance(p["pct"], (int, float)) or not (0 <= p["pct"] <= 100):
            return False, f"phase {p.get('id')!r} has an out-of-range pct: {p.get('pct')!r}"
        if p["status"] not in VALID_STATUSES:
            return False, f"phase {p.get('id')!r} has unknown status {p['status']!r} (expected one of {sorted(VALID_STATUSES)})"
        w = p.get("weight")
        if w is not None and not (isinstance(w, (int, float)) and w >= 0):
            return False, f"phase {p.get('id')!r} has a bad weight: {w!r} (must be a number >= 0)"
        fs = p.get("first_show")
        if fs is not None and not isinstance(fs, bool):
            return False, f"phase {p.get('id')!r} has a non-boolean first_show: {fs!r}"
    if not any(p.get("first_show") for p in phases):
        return False, "no phase is flagged first_show=true — the to-first-show bigbar would have nothing to average"
    progress = data.get("progress")
    if progress is not None and not isinstance(progress, dict):
        return False, "'progress' is present but not an object"
    return True, "ok"


def _weighted_avg(phases):
    """Weighted mean of phase pcts, rounded to a whole percent. weight defaults
    to 1 (a bad/negative weight also falls back to 1). Empty set -> 0."""
    num = den = 0.0
    for p in phases:
        w = p.get("weight", 1)
        if not isinstance(w, (int, float)) or w < 0:
            w = 1
        num += float(p["pct"]) * w
        den += w
    return round(num / den) if den else 0


def compute_progress(phases, progress_meta):
    """DETERMINISTICALLY derive the two bigbars from the phase pcts. The bigbar
    numbers are NEVER hand-authored — only the per-phase pct/weight/first_show
    and the note prose are. Editing a phase pct moves the relevant bar."""
    meta = progress_meta or {}
    first_show = [p for p in phases if p.get("first_show")]
    return {
        "to_first_show_pct": _weighted_avg(first_show),
        "to_first_show_note": meta.get("to_first_show_note") or DEFAULT_TO_FIRST_SHOW_NOTE,
        "full_roadmap_pct": _weighted_avg(phases),
        "full_roadmap_note": meta.get("full_roadmap_note") or DEFAULT_FULL_ROADMAP_NOTE,
    }


def _clean_phase(p):
    """Copy only the schema fields, in a stable order — drops any stray keys a
    hand-editor might leave in the block so briefing.json stays clean."""
    out = {"id": str(p["id"]), "name": p["name"], "status": p["status"], "pct": int(p["pct"])}
    if p.get("subtitle") is not None:
        out["subtitle"] = p["subtitle"]
    if p.get("state") is not None:
        out["state"] = p["state"]
    # Preserve schema field order the dashboard/briefing already use.
    return {"id": out["id"], "name": out["name"], "subtitle": out.get("subtitle", ""),
            "status": out["status"], "pct": out["pct"], "state": out.get("state", "")}


def apply(briefing, data, updated_date):
    """Return a NEW briefing dict with phases/progress/phases_updated replaced
    from the block — every other field preserved untouched. `phases` are copied
    verbatim (human-authored numbers); `progress` bigbars are COMPUTED from the
    phase pcts (never copied), so they can't go stale independently."""
    out = dict(briefing or {})
    out["phases"] = [_clean_phase(p) for p in data["phases"]]
    out["progress"] = compute_progress(data["phases"], data.get("progress"))
    if updated_date:
        out["phases_updated"] = updated_date
    return out


def _changed(before, after):
    """Did the fields this module owns actually change? Compares canonical JSON
    so key order / whitespace never trigger a spurious rewrite."""
    keys = ("phases", "progress", "phases_updated")
    b = {k: before.get(k) for k in keys}
    a = {k: after.get(k) for k in keys}
    return json.dumps(b, sort_keys=True) != json.dumps(a, sort_keys=True)


def sync(instance_config, kb_root, briefing, briefing_path, *, dry_run=False):
    """Main entry point, called from cycle.py.

    Reads the ```phases block from instance_config['content_source'] (resolved
    against kb_root), and — if valid and different — writes the updated
    phases/progress/phases_updated into briefing_path. Returns
    (briefing_for_this_cycle, result_dict). NEVER raises: on any problem it
    returns the ORIGINAL briefing and a result carrying the reason, so the
    cycle proceeds and the reason lands in the ledger.
    """
    briefing = briefing or {}
    src = instance_config.get("content_source")
    if not src:
        return briefing, {"synced": False, "reason": "instance has no content_source"}

    src_path = os.path.expanduser(src)
    if not os.path.isabs(src_path):
        src_path = os.path.join(kb_root, src_path)

    data, updated_date, err = parse_doc(src_path)
    if err:
        return briefing, {"synced": False, "reason": err, "source": src}

    ok, why = validate(data)
    if not ok:
        return briefing, {"synced": False, "reason": f"block invalid ({why}) — leaving briefing.json untouched", "source": src}

    new_briefing = apply(briefing, data, updated_date)
    if not _changed(briefing, new_briefing):
        return new_briefing, {"synced": True, "changed": False, "phases": len(new_briefing["phases"]),
                              "reason": "phase block already in sync", "source": src}

    if not dry_run:
        with open(briefing_path, "w") as f:
            json.dump(new_briefing, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return new_briefing, {"synced": True, "changed": True, "phases": len(new_briefing["phases"]),
                          "phases_updated": updated_date,
                          "reason": "phase board copied from content_source" + (" (dry-run: not written)" if dry_run else ""),
                          "source": src}


def _main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance", required=True, help="path to instance.json")
    ap.add_argument("--kb-root", default=os.path.expanduser("~/knowledge"))
    ap.add_argument("--dry-run", action="store_true", help="parse + classify, never write briefing.json")
    args = ap.parse_args()

    # Resolve the briefing path the same way cycle.py does, without importing it.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import cycle  # noqa: E402
    with open(os.path.expanduser(args.instance)) as f:
        cfg = json.load(f)
    paths = cycle.resolve_paths(cfg, args.kb_root)
    import dashboard  # noqa: E402
    briefing = dashboard.load_briefing(paths["briefing"]) or {}
    _, result = sync(cfg, args.kb_root, briefing, paths["briefing"], dry_run=args.dry_run)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
