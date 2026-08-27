import os
import sys
import tempfile
import textwrap
import unittest


LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, os.path.abspath(LIB))
import reconcile  # noqa: E402


class ReconcileTests(unittest.TestCase):
    def test_archived_v1_completion_remains_visible_but_legacy_does_not(self):
        with tempfile.TemporaryDirectory() as root:
            archive = os.path.join(root, "triggers", "archive")
            os.makedirs(archive)
            v1 = textwrap.dedent("""
                ---
                schema: work-item/v1
                id: delivered
                project: demo
                title: "Delivered outcome"
                status: completed
                priority: normal
                owner: codex
                done_when: The outcome is visible.
                verification: Inspect the result.
                evidence: commit abc1234
                completed_at: 2026-08-26
                ---
                ## Result

                Verified.
            """).strip()
            legacy = "---\ntitle: Demo old work\nstatus: completed\n---\n## Result\n\nOld.\n"
            with open(os.path.join(archive, "v1.md"), "w") as handle:
                handle.write(v1)
            with open(os.path.join(archive, "legacy.md"), "w") as handle:
                handle.write(legacy)
            done, in_flight, blocked = reconcile.collect_triggers(root, ["demo"], "demo")
        self.assertEqual([item["id"] for item in done], ["delivered"])
        self.assertEqual(in_flight, [])
        self.assertEqual(blocked, [])


if __name__ == "__main__":
    unittest.main()
