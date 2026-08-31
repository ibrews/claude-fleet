#!/usr/bin/env python3
"""Machine-checkable product maturity gates for demos, pilots, and public releases."""

import argparse
import json
import os


SCHEMA = "release-readiness/v1"
VALID_STATUS = {"pass", "fail", "unknown", "not_applicable"}
STAGES = [
    "functional", "visual", "reproducible", "human_usable",
    "portable", "packaging", "operations", "legal_release",
]
TARGET_STAGES = {
    "internal_demo": STAGES[:2],
    "external_pilot": STAGES[:7],
    "public": STAGES,
}


def load(path):
    try:
        with open(os.path.expanduser(path)) as handle:
            return json.load(handle), ""
    except (OSError, json.JSONDecodeError) as exc:
        return {}, str(exc)


def evaluate(manifest):
    issues = []
    target = manifest.get("release_target", "")
    if manifest.get("schema") != SCHEMA:
        issues.append("schema must be release-readiness/v1")
    if target not in TARGET_STAGES:
        issues.append("release_target must be internal_demo, external_pilot, or public")
    gates = manifest.get("gates") or {}
    stage_results = {}
    for stage in TARGET_STAGES.get(target, []):
        entries = gates.get(stage)
        if not isinstance(entries, list) or not entries:
            issues.append(f"{stage}: at least one gate is required")
            stage_results[stage] = "unknown"
            continue
        statuses = []
        for index, gate in enumerate(entries):
            status = gate.get("status", "unknown") if isinstance(gate, dict) else "unknown"
            statuses.append(status)
            if status not in VALID_STATUS:
                issues.append(f"{stage}[{index}]: invalid status {status!r}")
            if status == "pass" and not str(gate.get("evidence", "")).strip():
                issues.append(f"{stage}[{index}]: pass requires evidence")
        stage_results[stage] = (
            "fail" if "fail" in statuses else
            "unknown" if "unknown" in statuses or any(s not in VALID_STATUS for s in statuses) else
            "pass"
        )
    blockers = [stage for stage, status in stage_results.items() if status != "pass"]
    return {
        "schema": manifest.get("schema", ""),
        "product": manifest.get("product", ""),
        "release_target": target,
        "ready": not blockers and not issues,
        "stage_results": stage_results,
        "blockers": blockers,
        "issues": issues,
        "passed_stages": sum(status == "pass" for status in stage_results.values()),
        "required_stages": len(stage_results),
    }


def inspect(path):
    manifest, error = load(path)
    if error:
        return {"ready": False, "issues": [error], "blockers": ["manifest"],
                "stage_results": {}, "passed_stages": 0, "required_stages": 0}
    result = evaluate(manifest)
    result["manifest"] = os.path.expanduser(path)
    return result


def main():
    parser = argparse.ArgumentParser(description="Validate a release-readiness manifest")
    parser.add_argument("manifest")
    args = parser.parse_args()
    result = inspect(args.manifest)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ready"] else 1)


if __name__ == "__main__":
    main()
