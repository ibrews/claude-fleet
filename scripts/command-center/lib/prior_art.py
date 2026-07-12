#!/usr/bin/env python3
"""Prior-art gate: is this task build-shaped, and if so, was prior art checked?

The re-litigation failure this exists to stop (Alex's own framing): MetaHuman
grooms were solved in MetaHumanGodot, full-body motion in ACCVR/UnRealityKit —
then BOTH re-solved again in Persona Live AND the WebGPU client. A cheap
keyword heuristic can't tell whether a REAL search happened, only whether one
was DECLARED — so this is a gate on declaration, not a guarantee of diligence.
That's a deliberate, honest limitation: it converts "nobody thought to check"
into "you have to say what you checked," which is the actual failure mode
observed (missing habit, not missing willingness).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import reconcile  # noqa: E402  (reuse parse_frontmatter)

BUILD_VERBS = [
    r"\bbuild\b", r"\bimplement\b", r"\bcreate\b", r"\bdesign\b", r"\barchitect\b",
    r"\bsolve\b", r"\bwrite a\b", r"\bwrite an?\b.*\bfrom scratch\b", r"\bnew (pipeline|system|approach|solution)\b",
    r"\bfrom scratch\b", r"\bport\b", r"\bport(ing)?\b",
]
BUILD_RE = re.compile("|".join(BUILD_VERBS), re.IGNORECASE)

# Explicitly NOT build-shaped even if a build verb appears — these are the
# common false-positive shapes (verify/test/fix an existing thing).
NON_BUILD_RE = re.compile(
    r"\b(verify|test|check|debug|fix|diagnose|investigate|device[- ]test|confirm)\b",
    re.IGNORECASE,
)


def is_build_shaped(text):
    """Heuristic only — a declaration gate, not a diligence guarantee (see module docstring)."""
    if not text:
        return False
    if NON_BUILD_RE.search(text) and not BUILD_RE.search(text):
        return False
    if NON_BUILD_RE.search(text) and BUILD_RE.search(text):
        # Both present ("fix the build of X") — lean on whichever verb leads the text.
        build_pos = BUILD_RE.search(text).start()
        non_build_pos = NON_BUILD_RE.search(text).start()
        return build_pos < non_build_pos
    return bool(BUILD_RE.search(text))


def has_prior_art(fields):
    val = (fields.get("prior_art") or "").strip()
    return len(val) > 0


def check_trigger_text(title, task_text, fields):
    """Returns {build_shaped, has_prior_art, ok, reason}."""
    combined = f"{title} {task_text}"
    build_shaped = is_build_shaped(combined)
    prior_art_present = has_prior_art(fields)
    ok = (not build_shaped) or prior_art_present
    if ok:
        reason = "not build-shaped" if not build_shaped else "prior_art present"
    else:
        reason = (
            "build-shaped task with no prior_art field — kb-search + check "
            "projects/techniques-graph/master-index.md before proceeding"
        )
    return {"build_shaped": build_shaped, "has_prior_art": prior_art_present, "ok": ok, "reason": reason}


def check_trigger_file(path):
    fields, body = reconcile.parse_frontmatter(path)
    title = fields.get("title", "")
    task_match = re.search(r"## Task\s*\n+(.*?)(?:\n##|\Z)", body, re.DOTALL)
    task_text = task_match.group(1).strip() if task_match else body
    result = check_trigger_file_result = check_trigger_text(title, task_text, fields)
    result["file"] = path
    return result


if __name__ == "__main__":
    import glob
    import json

    if len(sys.argv) > 1:
        for path in sys.argv[1:]:
            print(json.dumps(check_trigger_file(path), indent=2))
    else:
        # Scan every real trigger in the KB — reports the current gap honestly
        # (expect ~all to fail: the field didn't exist before this was built).
        kb_root = os.path.expanduser("~/knowledge")
        flagged, clean = 0, 0
        for path in sorted(glob.glob(os.path.join(kb_root, "triggers", "*.md"))):
            r = check_trigger_file(path)
            if r["build_shaped"] and not r["ok"]:
                flagged += 1
                print(f"FLAG  {os.path.basename(path)}")
            else:
                clean += 1
        print(f"\n{flagged} build-shaped triggers missing prior_art, {clean} ok/not-build-shaped "
              f"(of {flagged + clean} total)")
