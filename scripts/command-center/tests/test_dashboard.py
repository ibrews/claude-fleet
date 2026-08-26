import os
import sys
import unittest


LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, os.path.abspath(LIB))
import dashboard  # noqa: E402


def sample_state():
    ticket = {
        "id": "demo", "title": "Choose release path", "priority": "high", "owner": "the operator",
        "blocked_on": "the operator decision", "next_check": "2026-08-25", "file": "triggers/demo.md",
    }
    return {
        "instance": "demo",
        "generated_at": "2026-08-24T12:00:00Z",
        "tracked_workers": [], "sessions_live": [], "sessions_stale_or_dead": [],
        "orchestrator_dispatched_active": [], "triggers_done": [], "triggers_in_flight": [],
        "triggers_blocked": [ticket], "inbox_open": [], "inbox_done": [],
        "needs_human": [ticket],
        "work_item_quality": {"active_count": 1, "valid_count": 1, "issue_count": 0,
                              "error_count": 0, "migration_issue_count": 0,
                              "legacy_count": 0, "issues": []},
        "delivery_summary": {"red_ci": 1, "dirty_repos": 0, "unintegrated_branches": 0},
        "delivery": {"enabled": True, "repositories": [{
            "name": "Demo", "github": "owner/repo", "path": "/tmp/demo", "dirty": False,
            "unintegrated_branches": [], "source": "local Git snapshot",
            "ci": {"status": "red", "source": "GitHub Actions", "workflows": [{}],
                   "red": [{"workflowName": "Tests", "url": "https://example.com/run"}], "error": ""},
        }]},
    }


class DashboardTests(unittest.TestCase):
    def test_project_dashboard_labels_machine_facts(self):
        output = dashboard.render(sample_state(), {}, "one cycle")
        self.assertIn("Delivery cockpit", output)
        self.assertIn("Needs the operator", output)
        self.assertIn("machine fact", output)
        self.assertIn("Unintegrated work", output)

    def test_index_is_a_fleet_delivery_cockpit(self):
        state = sample_state()
        output = dashboard.render_index([{
            "name": "demo", "description": "Demo", "workers": 0,
            "briefing": {}, "state": state, "delivery": state["delivery"],
        }])
        self.assertIn("Delivery <span class=\"b\">Cockpit</span>", output)
        self.assertIn("Delivery risks", output)
        self.assertIn("ticket errors", output)
        self.assertIn("migration warnings", output)
        self.assertIn("Project briefings", output)

    def test_index_deduplicates_same_ticket_across_legacy_keyword_matches(self):
        state = sample_state()
        instances = [
            {"name": name, "description": name, "workers": 0, "briefing": {},
             "state": state, "delivery": state["delivery"]}
            for name in ("alpha", "beta")
        ]
        output = dashboard.render_index(instances)
        self.assertIn("<b>1</b> need the operator", output)
        self.assertIn("<b>1</b> blocked tickets", output)


if __name__ == "__main__":
    unittest.main()
