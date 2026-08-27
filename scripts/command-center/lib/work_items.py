#!/usr/bin/env python3
"""Provider-neutral work-item parsing and validation for Command Center.

The fleet already uses ``triggers/*.md`` as durable work orders. This module
turns those files into a ticket contract without introducing a second backlog.
It deliberately uses only the standard library so every fleet machine can run
the mechanical reconciliation loop.
"""

import argparse
import glob
import json
import os
import re
from datetime import datetime, timezone


FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", re.DOTALL)
VALID_STATUSES = {"pending", "in_progress", "review", "blocked", "completed", "cancelled"}
VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
TERMINAL_STATUSES = {"completed", "cancelled"}
SCHEMA_V1 = "work-item/v1"
PLACEHOLDER_RE = re.compile(r"<[^>]+>|\b(?:tbd|todo|placeholder)\b", re.IGNORECASE)

# Old triggers predate a shared lifecycle and contain prose-like states. Keep
# their raw value for migration, but give the cockpit one deterministic state.
LEGACY_STATUS_MAP = {
    "superseded": "cancelled",
    "mostly-superseded": "cancelled",
    "informational": "cancelled",
    "deferred": "blocked",
    "partial": "in_progress",
    "y-merged-stress-pending": "in_progress",
}


def _strip_inline_comment(value):
    """Strip an unquoted YAML-style inline comment from a scalar."""
    quote = None
    for index, char in enumerate(value):
        if char in "\"'":
            quote = None if quote == char else (char if quote is None else quote)
        elif char == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.strip()


def parse_frontmatter_text(text):
    """Parse the small YAML subset used by trigger files.

    The old parser treated ``done_when: >`` as the literal value ``>`` and
    discarded its indented lines. Supporting block scalars here is essential:
    the observable completion condition is the most important ticket field.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw, body = match.group(1), match.group(2)
    fields = {}
    lines = raw.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line or line.lstrip().startswith("#") or line[:1].isspace() or ":" not in line:
            index += 1
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        value = _strip_inline_comment(raw_value.strip())
        if value in {">", "|", ">-", "|-", ">+", "|+"}:
            folded = value.startswith(">")
            block = []
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if candidate and not candidate[:1].isspace():
                    break
                if candidate.lstrip().startswith("#"):
                    index += 1
                    continue
                block.append(candidate.strip())
                index += 1
            fields[key] = (" " if folded else "\n").join(block).strip()
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
        index += 1
    return fields, body


def parse_frontmatter(path):
    with open(path, errors="replace") as handle:
        return parse_frontmatter_text(handle.read())


def _section(body, heading):
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(body)
    return match.group(1).strip() if match else ""


def _present(value):
    value = str(value or "").strip()
    return bool(value and value not in {">", "|"} and not PLACEHOLDER_RE.search(value))


def _is_date(value):
    if not value:
        return False
    try:
        datetime.strptime(value[:10], "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def derive_owner(fields):
    for key in ("owner", "claimed_by", "target"):
        if _present(fields.get(key)) and fields[key] not in {"any", "?"}:
            return fields[key], key
    return "", ""


def normalize_status(raw_status, schema="legacy"):
    value = str(raw_status or "pending").strip()
    if value in VALID_STATUSES:
        return value
    if schema != SCHEMA_V1:
        if value in LEGACY_STATUS_MAP:
            return LEGACY_STATUS_MAP[value]
        # Historical job summaries commonly embedded progress in the status
        # field. They remain open migration debt, never fabricated completion.
        return "in_progress"
    return value


def normalize_priority(raw_priority, schema="legacy"):
    value = str(raw_priority or "normal").strip()
    if value in VALID_PRIORITIES:
        return value
    if schema != SCHEMA_V1 and value == "medium":
        return "normal"
    return value


def needs_human(fields):
    status = fields.get("status", "pending")
    owner = fields.get("owner", "").strip().lower()
    gate_text = " ".join(
        fields.get(key, "") for key in ("blocked_on", "acceptance")
    ).lower()
    explicit_human = fields.get("human_gate", "").lower() in {"true", "yes", "required"}
    # `target: your-laptop` names a machine, not the operator. Only the accountable owner
    # or explicit gate text can put an item in the human-decision queue.
    named_human = status in {"blocked", "review"} and (
        owner in {"operator", "human", "stakeholder"} or any(
            token in gate_text for token in ("operator", "human", "owner decision", "stakeholder")
        )
    )
    approval_wait = fields.get("tier") == "approve" and status in {"blocked", "review"}
    return explicit_human or named_human or approval_wait


def validate(fields, body=""):
    """Return structured issues without blocking legacy tickets from rendering."""
    issues = []

    def add(field, message, severity="warning"):
        issues.append({"field": field, "message": message, "severity": severity})

    schema = fields.get("schema", "legacy")
    raw_status = fields.get("status", "pending")
    status = normalize_status(raw_status, schema)
    raw_priority = fields.get("priority", "normal")
    priority = normalize_priority(raw_priority, schema)

    for key in ("id", "title", "status", "priority"):
        if not _present(fields.get(key)):
            add(key, f"missing {key}", "error" if schema == SCHEMA_V1 else "warning")
    if raw_status not in VALID_STATUSES:
        add(
            "status", f"legacy status needs migration: {raw_status}",
            "error" if schema == SCHEMA_V1 else "warning",
        )
    if raw_priority not in VALID_PRIORITIES:
        add(
            "priority", f"priority needs migration: {raw_priority}",
            "error" if schema == SCHEMA_V1 else "warning",
        )

    owner, owner_source = derive_owner(fields)
    required_v1 = ("project", "owner", "done_when", "verification")
    for key in required_v1:
        value = owner if key == "owner" else fields.get(key)
        if not _present(value):
            severity = "error" if schema == SCHEMA_V1 else "warning"
            add(key, f"missing {key}", severity)
    if owner and owner_source != "owner":
        add("owner", f"owner derived from {owner_source}; make it explicit")

    if raw_status == "blocked":
        if not _present(fields.get("blocked_on")):
            add(
                "blocked_on", "blocked ticket needs one concrete unblock condition",
                "error" if schema == SCHEMA_V1 else "warning",
            )
        if not _is_date(fields.get("next_check")):
            add(
                "next_check", "blocked ticket needs a YYYY-MM-DD next-check date",
                "error" if schema == SCHEMA_V1 else "warning",
            )
    if status in {"review", "completed"} and not _present(fields.get("evidence")):
        add("evidence", f"{status} ticket needs verification evidence",
            "error" if schema == SCHEMA_V1 else "warning")
    if status == "completed":
        if not _is_date(fields.get("completed_at")):
            add("completed_at", "completed ticket needs a completion date", "error")
        result = _section(body, "Result")
        if not _present(result) or "Filled in by executing machine" in result:
            add("result", "completed ticket needs a substantive Result section", "error")

    return issues


def parse_trigger(path, kb_root=None):
    fields, body = parse_frontmatter(path)
    owner, owner_source = derive_owner(fields)
    issues = validate(fields, body)
    relpath = os.path.relpath(path, kb_root) if kb_root else path
    schema = fields.get("schema", "legacy")
    raw_status = fields.get("status", "pending")
    raw_priority = fields.get("priority", "normal")
    return {
        "file": relpath,
        "id": fields.get("id") or os.path.basename(path),
        "schema": schema,
        "project": fields.get("project", ""),
        "title": fields.get("title", ""),
        "status": normalize_status(raw_status, schema),
        "raw_status": raw_status,
        "priority": normalize_priority(raw_priority, schema),
        "raw_priority": raw_priority,
        "owner": owner,
        "owner_source": owner_source,
        "target": fields.get("target", ""),
        "claimed_by": fields.get("claimed_by", ""),
        "claimed_at": fields.get("claimed_at", ""),
        "done_when": fields.get("done_when", ""),
        "verification": fields.get("verification", ""),
        "evidence": fields.get("evidence", ""),
        "blocked_on": fields.get("blocked_on", ""),
        "next_check": fields.get("next_check", ""),
        "repo": fields.get("repo", ""),
        "branch": fields.get("branch", ""),
        "acceptance": fields.get("acceptance", ""),
        "human_gate": fields.get("human_gate", ""),
        "completed_at": fields.get("completed_at", ""),
        "needs_human": needs_human(fields),
        "schema_issues": issues,
        "result": _section(body, "Result"),
        "fields": fields,
        "body": body,
    }


def scan(kb_root):
    active_paths = sorted(glob.glob(os.path.join(kb_root, "triggers", "*.md")))
    items = [
        parse_trigger(path, kb_root) for path in active_paths
        if os.path.basename(path).lower() != "readme.md"
    ]
    # The inbox flush archives completed triggers quickly. Keep v1 closures in
    # the evidence audit after archival without importing the entire legacy
    # archive back into the active queue and project matchers.
    for path in sorted(glob.glob(os.path.join(kb_root, "triggers", "archive", "*.md"))):
        fields, _ = parse_frontmatter(path)
        if fields.get("schema") == SCHEMA_V1:
            items.append(parse_trigger(path, kb_root))
    return items


def summarize(items):
    active = [item for item in items if item["status"] not in TERMINAL_STATUSES]
    completed_v1 = [
        item for item in items
        if item["status"] == "completed" and item["schema"] == SCHEMA_V1
    ]
    issues = [
        {"id": item["id"], "file": item["file"], **issue}
        for item in active for issue in item["schema_issues"]
    ]
    closure_issues = [
        {"id": item["id"], "file": item["file"], **issue}
        for item in completed_v1 for issue in item["schema_issues"]
    ]
    return {
        "active_count": len(active),
        "valid_count": sum(
            not any(issue["severity"] == "error" for issue in item["schema_issues"])
            for item in active
        ),
        "contract_ready_count": sum(
            item["schema"] == SCHEMA_V1 and not item["schema_issues"] for item in active
        ),
        "issue_count": len(issues),
        "error_count": sum(issue["severity"] == "error" for issue in issues),
        "migration_issue_count": sum(issue["severity"] == "warning" for issue in issues),
        "legacy_count": sum(item["schema"] != SCHEMA_V1 for item in active),
        "issues": issues,
        "completed_v1_count": len(completed_v1),
        "verified_closure_count": sum(not item["schema_issues"] for item in completed_v1),
        "closure_issue_count": len(closure_issues),
        "closure_error_count": sum(
            issue["severity"] == "error" for issue in closure_issues
        ),
        "closure_issues": closure_issues,
    }


def main():
    parser = argparse.ArgumentParser(description="Validate Command Center trigger tickets")
    parser.add_argument("--kb-root", default=os.path.expanduser("~/knowledge"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero for warnings as well as errors")
    args = parser.parse_args()
    items = scan(args.kb_root)
    report = summarize(items)
    report["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"{report['active_count']} active tickets · "
            f"{report['contract_ready_count']} v1-ready · {report['error_count']} errors · "
            f"{report['migration_issue_count']} migration warnings · "
            f"{report['verified_closure_count']}/{report['completed_v1_count']} verified v1 closures"
        )
        for issue in report["issues"] + report["closure_issues"]:
            print(f"{issue['severity'].upper():7} {issue['file']}: {issue['message']}")
    if report["error_count"] or report["closure_error_count"] or (
        args.strict and (report["issue_count"] or report["closure_issue_count"])
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
