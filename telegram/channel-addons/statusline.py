#!/usr/bin/env python3
"""statusline.py — Claude Code status line + usage-state bridge.

Claude Code pipes status-line JSON (model, workspace, rate_limits, ...) to this
script on every interactive update. We do two jobs:

  1. Persist rate-limit state to ~/.claude/usage-state.json — this is the ONLY
     place CC exposes subscription rate limits programmatically. The Telegram
     /usage command and ~/.claude/hooks/rate-limit-autosleep.sh read it.
  2. Print the visible status line: model | dir | 5h % | wk %

rate_limits is only present for Pro/Max-authenticated sessions after the first
API response — everything here is defensive about missing fields.
"""
import json
import os
import sys
import tempfile
import time

try:
    d = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)

state = {
    "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "model": (d.get("model") or {}).get("display_name"),
    "rate_limits": d.get("rate_limits"),
}
path = os.path.join(os.path.expanduser("~"), ".claude", "usage-state.json")
try:
    # Atomic write — many concurrent sessions update this; last writer wins,
    # readers never see a torn file.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".usage-state-")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)
except Exception:
    pass

model = (d.get("model") or {}).get("display_name") or "?"
cwd = ((d.get("workspace") or {}).get("current_dir") or "").rstrip("/")
parts = [model, cwd.split("/")[-1] or "~"]
rl = d.get("rate_limits") or {}
for key, label in (("five_hour", "5h"), ("seven_day", "wk")):
    pct = (rl.get(key) or {}).get("used_percentage")
    if pct is not None:
        parts.append(f"{label} {round(pct)}%")
print(" | ".join(parts))
