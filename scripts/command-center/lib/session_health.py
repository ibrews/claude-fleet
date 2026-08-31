#!/usr/bin/env python3
"""Deterministic Claude transcript context-health inspection.

Claude records the prompt-cache footprint on assistant events. The sum of
input, cache-read, and cache-creation tokens is the best locally observable
estimate of the active context. Reading it costs no model tokens.
"""

import argparse
import glob
import json
import os


def usage_context_tokens(usage):
    usage = usage or {}
    return sum(int(usage.get(key) or 0) for key in (
        "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
    ))


def inspect_transcript(path, *, warning_at=450000, rollover_at=520000, context_limit=600000):
    latest = None
    compactions = 0
    with open(path, errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            marker = " ".join(str(event.get(key, "")) for key in ("type", "subtype"))
            if "compact" in marker.lower():
                compactions += 1
            message = event.get("message") or {}
            usage = message.get("usage")
            if event.get("type") != "assistant" or not usage:
                continue
            latest = {
                "session_id": event.get("sessionId") or os.path.basename(path).split(".")[0],
                "model": message.get("model", ""),
                "thinking": event.get("effort", ""),
                "context_tokens": usage_context_tokens(usage),
                "timestamp": event.get("timestamp", ""),
            }
    if latest is None:
        return {
            "session_id": os.path.basename(path).split(".")[0], "status": "unknown",
            "context_tokens": None, "context_percent": None, "transcript": path,
            "compactions": compactions,
        }
    tokens = latest["context_tokens"]
    status = "rollover" if tokens >= rollover_at else "warning" if tokens >= warning_at else "healthy"
    latest.update({
        "status": status,
        "context_percent": round(tokens * 100.0 / context_limit, 1),
        "warning_at": warning_at,
        "rollover_at": rollover_at,
        "context_limit": context_limit,
        "transcript": path,
        "compactions": compactions,
    })
    return latest


def find_transcript(root, session_id):
    candidates = [session_id]
    # Fleet Bus roles often use a human-readable alias such as
    # `knowledge-4800e94c-primary`; Claude's transcript uses the full UUID.
    # Resolve the embedded 8-char UUID prefix deterministically.
    parts = str(session_id).split("-")
    candidates.extend(part for part in parts if len(part) == 8 and all(
        char in "0123456789abcdefABCDEF" for char in part
    ))
    matches = []
    for candidate in candidates:
        matches.extend(glob.glob(os.path.join(os.path.expanduser(root), "*", f"{candidate}.jsonl")))
        matches.extend(glob.glob(os.path.join(os.path.expanduser(root), "*", f"{candidate}*.jsonl")))
    return max(set(matches), key=os.path.getmtime) if matches else None


def inspect_session(root, session_id, **thresholds):
    path = find_transcript(root, session_id)
    if not path:
        return {"session_id": session_id, "status": "missing", "context_tokens": None,
                "context_percent": None, "transcript": ""}
    return inspect_transcript(path, **thresholds)


def main():
    parser = argparse.ArgumentParser(description="Report a Claude session's context health")
    parser.add_argument("session_id")
    parser.add_argument("--root", default="~/.claude/projects")
    parser.add_argument("--warning-at", type=int, default=450000)
    parser.add_argument("--rollover-at", type=int, default=520000)
    parser.add_argument("--context-limit", type=int, default=600000)
    args = parser.parse_args()
    print(json.dumps(inspect_session(
        args.root, args.session_id, warning_at=args.warning_at,
        rollover_at=args.rollover_at, context_limit=args.context_limit,
    ), indent=2))


if __name__ == "__main__":
    main()
