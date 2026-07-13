#!/bin/bash
# prior-art-gate-check.sh — PreToolUse(Write) hook.
#
# Backstop for the Command Center's prior-art gate (see intelligence/decisions/
# 2026-07-12-command-center-orchestrator.md). departments/engineering/
# command-center/lib/dispatch.py already refuses to write orchestrator-authored
# trigger files that look build-shaped and lack a prior_art field — but a
# human or a non-orchestrator session can still Write a trigger file directly,
# bypassing that Python check entirely. This hook is the net for THAT path:
# warns (via additionalContext, non-blocking — same soft pattern as
# vendor-source-dispatch-reminder.sh) when Claude is about to Write a new file
# under triggers/ whose title/task text looks build-shaped and has no
# prior_art: field filled in.
#
# WHY soft, not a hard block: the heuristic (departments/engineering/
# command-center/lib/prior_art.py) is a declaration gate, not a diligence
# guarantee — it can't verify a real kb-search happened, only that the field
# is non-empty. A hard block would just train sessions to fill in a throwaway
# string to get past it. A nudge that names the actual lookup surface
# (kb-search + the techniques graph) is honest about what it can and can't
# enforce.
#
# Canonical copy: ~/knowledge/departments/engineering/hooks/prior-art-gate-check.sh
set -u

PAYLOAD=$(cat)

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -z "$PY" ] && exit 0

KB_ROOT="${KB_ROOT:-$HOME/knowledge}"
PRIOR_ART_PY="$KB_ROOT/departments/engineering/command-center/lib/prior_art.py"
[ -f "$PRIOR_ART_PY" ] && export PRIOR_ART_PY

PAYLOAD="$PAYLOAD" "$PY" <<'PYEOF'
import json, os, re, sys

try:
    d = json.loads(os.environ.get("PAYLOAD") or "{}")
except Exception:
    sys.exit(0)

if d.get("tool_name") != "Write":
    sys.exit(0)

ti = d.get("tool_input") or {}
file_path = str(ti.get("file_path", ""))
content = str(ti.get("content", ""))

# Only fires on new trigger files, not edits to arbitrary content.
if not re.search(r"[\\/]triggers[\\/][^\\/]+\.md$", file_path):
    sys.exit(0)

prior_art_py = os.environ.get("PRIOR_ART_PY", "")
if not prior_art_py or not os.path.exists(prior_art_py):
    sys.exit(0)  # command-center not installed on this machine/checkout — nothing to check against

lib_dir = os.path.dirname(prior_art_py)
sys.path.insert(0, lib_dir)
try:
    import prior_art  # noqa: E402
except Exception:
    sys.exit(0)

# Parse the frontmatter/body straight out of the about-to-be-written content
# (the file doesn't exist yet — Write hasn't run — so read it from tool_input,
# not from disk).
m = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
if not m:
    sys.exit(0)  # not frontmatter-shaped, not our concern

fields = {}
for line in m.group(1).splitlines():
    if ":" not in line:
        continue
    k, _, v = line.partition(":")
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    fields[k.strip()] = v

title = fields.get("title", "")
task_match = re.search(r"## Task\s*\n+(.*?)(?:\n##|\Z)", m.group(2), re.DOTALL)
task_text = task_match.group(1).strip() if task_match else ""

result = prior_art.check_trigger_text(title, task_text, fields)
if result["ok"]:
    sys.exit(0)

msg = (
    "prior-art-gate-check: this new trigger file looks BUILD-SHAPED "
    f"(title: \"{title[:80]}\") and its prior_art: field is empty. Before claiming/dispatching "
    "this, kb-search the topic and check projects/techniques-graph/master-index.md — this is "
    "the fleet's re-litigation guard (MetaHuman grooms and full-body IK were each independently "
    "re-solved 3-4x across projects before this existed). If you've already checked, just fill "
    "in prior_art: with what you found (or 'confirmed new, no prior art') and this won't fire "
    "again for this file. Non-blocking — this is a reminder, not a hard stop."
)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": msg}}))
PYEOF
exit 0
