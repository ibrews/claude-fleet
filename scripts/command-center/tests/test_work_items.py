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


if __name__ == "__main__":
    unittest.main()
