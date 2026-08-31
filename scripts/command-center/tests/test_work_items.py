import os
import sys
import tempfile
import textwrap
import unittest


LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, os.path.abspath(LIB))
import work_items  # noqa: E402


class WorkItemTests(unittest.TestCase):
    def write_trigger(self, frontmatter, body="## Result\n\nVerified on the real surface."):
        temp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        temp.write(f"---\n{frontmatter}\n---\n{body}\n")
        temp.close()
        self.addCleanup(lambda: os.path.exists(temp.name) and os.unlink(temp.name))
        return temp.name

    def test_multiline_done_when_and_inline_comments_are_parsed(self):
        path = self.write_trigger(textwrap.dedent("""
            schema: work-item/v1
            id: demo-2026-08-24
            project: demo
            title: "Demo ticket"
            status: pending # lifecycle note
            priority: normal
            owner: your-laptop
            done_when: >
              A real dashboard renders the delivery state
              and links its evidence.
            verification: python3 -m unittest
        """).strip())
        item = work_items.parse_trigger(path)
        self.assertEqual(item["status"], "pending")
        self.assertEqual(
            item["done_when"],
            "A real dashboard renders the delivery state and links its evidence.",
        )
        self.assertEqual(item["schema_issues"], [])

    def test_blocked_v1_ticket_requires_unblock_and_next_check(self):
        path = self.write_trigger(textwrap.dedent("""
            schema: work-item/v1
            id: blocked-2026-08-24
            project: demo
            title: "Blocked ticket"
            status: blocked
            priority: high
            owner: operator
            done_when: The device shows the expected result.
            verification: Human checks the device.
        """).strip(), body="## Result\n\n")
        item = work_items.parse_trigger(path)
        fields = {issue["field"] for issue in item["schema_issues"]}
        self.assertIn("blocked_on", fields)
        self.assertIn("next_check", fields)
        self.assertTrue(item["needs_human"])

    def test_legacy_owner_is_derived_but_reported(self):
        path = self.write_trigger(textwrap.dedent("""
            id: legacy-2026-08-24
            title: "Legacy ticket"
            status: pending
            priority: normal
            target: alpha
            done_when: A real check passes.
        """).strip())
        item = work_items.parse_trigger(path)
        self.assertEqual(item["owner"], "alpha")
        self.assertEqual(item["owner_source"], "target")
        self.assertTrue(any(issue["field"] == "owner" for issue in item["schema_issues"]))

    def test_legacy_lifecycle_is_normalized_without_a_blocking_error(self):
        path = self.write_trigger(textwrap.dedent("""
            id: legacy-partial-2026-08-24
            title: "Legacy partial ticket"
            status: partial
            priority: medium
            target: alpha
        """).strip())
        item = work_items.parse_trigger(path)
        self.assertEqual(item["raw_status"], "partial")
        self.assertEqual(item["status"], "in_progress")
        self.assertEqual(item["priority"], "normal")
        self.assertFalse(any(
            issue["severity"] == "error" for issue in item["schema_issues"]
        ))

    def test_superseded_legacy_ticket_is_terminal(self):
        path = self.write_trigger(textwrap.dedent("""
            title: "Old resume brief"
            status: superseded
        """).strip())
        item = work_items.parse_trigger(path)
        report = work_items.summarize([item])
        self.assertEqual(item["status"], "cancelled")
        self.assertEqual(report["active_count"], 0)

    def test_your_laptop_target_is_not_a_human_gate(self):
        fields = {
            "owner": "knowledge-session",
            "target": "your-laptop",
            "status": "in_progress",
            "human_gate": "false",
        }
        self.assertFalse(work_items.needs_human(fields))

    def test_completed_v1_ticket_stays_in_closure_integrity_audit(self):
        path = self.write_trigger(textwrap.dedent("""
            schema: work-item/v1
            id: weak-closure-2026-08-26
            project: demo
            title: "Weak closure"
            status: completed
            priority: normal
            owner: codex
            done_when: The live surface proves the outcome.
            verification: Inspect the live surface.
            completed_at: 2026-08-26
        """).strip())
        item = work_items.parse_trigger(path)
        report = work_items.summarize([item])
        self.assertEqual(report["active_count"], 0)
        self.assertEqual(report["closure_error_count"], 1)
        self.assertEqual(report["verified_closure_count"], 0)

    def test_scan_retains_archived_v1_closures_without_legacy_archive(self):
        with tempfile.TemporaryDirectory() as root:
            archive = os.path.join(root, "triggers", "archive")
            os.makedirs(archive)
            v1 = textwrap.dedent("""
                ---
                schema: work-item/v1
                id: verified-closure
                project: demo
                title: "Verified closure"
                status: completed
                priority: normal
                owner: codex
                done_when: The outcome is visible.
                verification: Inspect the result.
                evidence: commit abc1234
                completed_at: 2026-08-26
                ---
                ## Result

                Verified on the real surface.
            """).strip()
            legacy = "---\ntitle: Legacy\nstatus: completed\n---\n## Result\n\nOld.\n"
            with open(os.path.join(archive, "v1.md"), "w") as handle:
                handle.write(v1)
            with open(os.path.join(archive, "legacy.md"), "w") as handle:
                handle.write(legacy)
            items = work_items.scan(root)
        self.assertEqual([item["id"] for item in items], ["verified-closure"])

    def test_v2_requires_explicit_route_context_and_release_target(self):
        path = self.write_trigger(textwrap.dedent("""
            schema: work-item/v2
            id: routed-2026-08-31
            project: demo
            title: "Routed ticket"
            status: pending
            priority: normal
            owner: orchestrator
            done_when: The artifact passes its acceptance suite.
            verification: Run the acceptance suite.
            executor: claude-worker
            machine: beta
            model: sonnet
            thinking: high
            route_basis: fleet/dispatch.md UE5 Live Tasks
            context_limit: 600000
            rollover_at: 500000
            release_target: external_pilot
        """).strip())
        item = work_items.parse_trigger(path)
        self.assertEqual(item["schema_issues"], [])
        self.assertEqual(item["rollover_at"], 500000)

    def test_v2_rejects_rollover_at_or_above_context_limit(self):
        path = self.write_trigger(textwrap.dedent("""
            schema: work-item/v2
            id: bad-rollover-2026-08-31
            project: demo
            title: "Bad rollover"
            status: pending
            priority: normal
            owner: orchestrator
            done_when: The artifact passes.
            verification: Run tests.
            executor: claude-worker
            machine: beta
            model: sonnet
            thinking: high
            route_basis: fleet/dispatch.md
            context_limit: 600000
            rollover_at: 600000
            release_target: external_pilot
        """).strip())
        issues = work_items.parse_trigger(path)["schema_issues"]
        self.assertTrue(any(issue["field"] == "rollover_at" for issue in issues))


if __name__ == "__main__":
    unittest.main()
