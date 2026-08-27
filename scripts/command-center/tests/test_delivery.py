import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock


LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, os.path.abspath(LIB))
import delivery  # noqa: E402


class DeliveryTests(unittest.TestCase):
    def git(self, path, *args):
        subprocess.run(["git", "-C", path, *args], check=True, capture_output=True, text=True)

    def test_local_repo_reports_dirty_and_unintegrated_branch(self):
        with tempfile.TemporaryDirectory() as repo:
            self.git(repo, "init", "-b", "main")
            self.git(repo, "config", "user.email", "test@example.com")
            self.git(repo, "config", "user.name", "Test")
            with open(os.path.join(repo, "README.md"), "w") as handle:
                handle.write("base\n")
            self.git(repo, "add", "README.md")
            self.git(repo, "commit", "-m", "base")
            self.git(repo, "switch", "-c", "feature")
            with open(os.path.join(repo, "feature.txt"), "w") as handle:
                handle.write("feature\n")
            self.git(repo, "add", "feature.txt")
            self.git(repo, "commit", "-m", "feature")
            with open(os.path.join(repo, "dirty.txt"), "w") as handle:
                handle.write("dirty\n")

            result = delivery.inspect_local_repo({
                "name": "Demo", "path": repo, "default_branch": "main",
            })
            self.assertTrue(result["available"])
            self.assertTrue(result["dirty"])
            self.assertEqual(result["unintegrated_branches"][0]["branch"], "feature")
            self.assertEqual(result["unintegrated_branches"][0]["unique_commits"], 1)

    def test_ci_uses_latest_run_per_workflow(self):
        runs = [
            {"workflowName": "Tests", "status": "completed", "conclusion": "failure", "url": "old"},
            {"workflowName": "Tests", "status": "completed", "conclusion": "success", "url": "older"},
            {"workflowName": "Docs", "status": "completed", "conclusion": "success", "url": "docs"},
        ]
        with mock.patch.object(delivery, "_run", return_value=(0, json.dumps(runs), "")):
            result = delivery.inspect_ci("owner/repo")
        self.assertEqual(result["status"], "red")
        self.assertEqual(len(result["workflows"]), 2)
        self.assertEqual(result["red"][0]["workflowName"], "Tests")

    def test_missing_checkout_is_counted_as_unavailable_not_clean(self):
        result = delivery.collect({
            "delivery": {"enabled": True, "repositories": [{
                "name": "Missing", "path": "/definitely/not/present",
            }]}
        })
        summary = delivery.summarize(result)
        self.assertEqual(summary["local_unavailable"], 1)
        self.assertEqual(summary["dirty_repos"], 0)

    def write_host_report(self, root, generated_at):
        report_dir = os.path.join(root, "host-evidence")
        os.makedirs(report_dir)
        with open(os.path.join(report_dir, "your-laptop.json"), "w") as handle:
            json.dump({
                "schema": "host-evidence/v1",
                "machine": "your-laptop",
                "generated_at": generated_at,
                "repositories": [{
                    "project": "demo",
                    "name": "Demo",
                    "github": "owner/repo",
                    "path": "/remote/demo",
                    "available": True,
                    "dirty": False,
                    "dirty_entries": 0,
                    "current_branch": "main",
                    "unintegrated_branches": [],
                    "error": "",
                }],
            }, handle)

    def test_fresh_host_report_closes_collector_checkout_gap(self):
        with tempfile.TemporaryDirectory() as state_root:
            self.write_host_report(
                state_root, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            result = delivery.collect({
                "name": "demo",
                "delivery": {"enabled": True, "repositories": [{
                    "name": "Demo", "path": "/not/on/collector", "github": "owner/repo",
                    "host": "your-laptop",
                }]},
            }, evidence_root=state_root)
        repo = result["repositories"][0]
        self.assertTrue(repo["available"])
        self.assertEqual(repo["telemetry_status"], "fresh")
        self.assertEqual(repo["evidence_host"], "your-laptop")
        self.assertIn("host report", repo["source"])
        self.assertEqual(delivery.summarize(result)["local_unavailable"], 0)

    def test_stale_host_report_is_a_risk_not_a_clean_fact(self):
        with tempfile.TemporaryDirectory() as state_root:
            stale = datetime.now(timezone.utc) - timedelta(hours=2)
            self.write_host_report(state_root, stale.strftime("%Y-%m-%dT%H:%M:%SZ"))
            result = delivery.collect({
                "name": "demo",
                "delivery": {
                    "enabled": True,
                    "report_max_age_minutes": 15,
                    "repositories": [{
                        "name": "Demo", "path": "/not/on/collector", "github": "owner/repo",
                        "host": "your-laptop",
                    }],
                },
            }, evidence_root=state_root)
        repo = result["repositories"][0]
        self.assertEqual(repo["telemetry_status"], "stale")
        self.assertGreater(repo["report_age_minutes"], 100)
        self.assertEqual(delivery.summarize(result)["stale_reports"], 1)


if __name__ == "__main__":
    unittest.main()
