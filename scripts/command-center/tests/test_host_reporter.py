import json
import os
import sys
import tempfile
import unittest
from unittest import mock


ENGINE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ENGINE)
import host_reporter  # noqa: E402


class HostReporterTests(unittest.TestCase):
    def write_instance(self, root, project, repositories):
        directory = os.path.join(root, "projects", project, "command-center")
        os.makedirs(directory)
        with open(os.path.join(directory, "instance.json"), "w") as handle:
            json.dump({
                "name": project,
                "delivery": {"enabled": True, "repositories": repositories},
            }, handle)

    def test_discovery_only_collects_explicit_machine_assignments(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_instance(root, "demo", [
                {"name": "Mine", "host": "your-laptop", "path": "/mine"},
                {"name": "Theirs", "host": "alpha", "path": "/theirs"},
                {"name": "Legacy", "path": "/unassigned"},
            ])
            repositories = host_reporter.discover_repository_configs(root, "your-laptop")
        self.assertEqual([repo["name"] for repo in repositories], ["Mine"])
        self.assertEqual(repositories[0]["project"], "demo")

    def test_report_preserves_project_identity_and_machine_fact(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_instance(root, "demo", [
                {"name": "Mine", "host": "your-laptop", "path": "/mine", "github": "owner/repo"},
            ])
            with mock.patch.object(
                host_reporter.delivery, "inspect_local_repo",
                return_value={"name": "Mine", "available": True, "dirty": False},
            ):
                report = host_reporter.build_report(root, "your-laptop")
        self.assertEqual(report["schema"], "host-evidence/v1")
        self.assertEqual(report["machine"], "your-laptop")
        self.assertEqual(report["repositories"][0]["project"], "demo")
        self.assertEqual(report["repositories"][0]["github"], "owner/repo")

    def test_atomic_write_round_trips_report(self):
        report = {
            "schema": "host-evidence/v1", "machine": "your-laptop",
            "generated_at": "2026-08-26T12:00:00Z", "repositories": [],
        }
        with tempfile.TemporaryDirectory() as state_root:
            destination = host_reporter.write_report(report, state_root)
            with open(destination) as handle:
                written = json.load(handle)
        self.assertEqual(written, report)


if __name__ == "__main__":
    unittest.main()
