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
        "delivery_summary": {"red_ci": 1, "dirty_repos": 0, "unintegrated_branches": 0,
                             "local_unavailable": 0},
        "delivery": {"enabled": True, "repositories": [{
            "name": "Demo", "github": "owner/repo", "path": "/tmp/demo", "dirty": False,
            "available": True, "unintegrated_branches": [], "source": "local Git snapshot",
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
        self.assertIn(".card-grid{grid-template-columns:minmax(0,1fr)}", output)

    def test_index_includes_accessible_operator_walkthrough(self):
        state = sample_state()
        output = dashboard.render_index([{
            "name": "demo", "description": "Demo", "workers": 0,
            "briefing": {}, "state": state, "delivery": state["delivery"],
        }])
        self.assertIn("Run 3-minute tour", output)
        self.assertIn('aria-labelledby="cc-tour-title"', output)
        self.assertEqual(output.count('data-tour-panel="'), 6)
        self.assertIn("Machine fact", output)
        self.assertIn("A ticket closes only with evidence", output)
        self.assertIn("full Scrum ceremony is optional", output)
        self.assertIn("ArrowRight", output)

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

    def test_unavailable_local_repo_is_an_explicit_host_gap(self):
        state = sample_state()
        repo = state["delivery"]["repositories"][0]
        repo.update({"available": False, "error": "checkout not present on this host"})
        state["delivery_summary"]["local_unavailable"] = 1
        output = dashboard.render_index([{
            "name": "demo", "description": "Demo", "workers": 0,
            "briefing": {}, "state": state, "delivery": state["delivery"],
        }])
        self.assertIn("host gap", output)
        self.assertIn("checkout not present on this host", output)

    def test_stale_host_report_is_visible_as_a_delivery_risk(self):
        state = sample_state()
        repo = state["delivery"]["repositories"][0]
        repo.update({
            "telemetry_status": "stale", "evidence_host": "your-laptop",
            "report_age_minutes": 91, "source": "your-laptop host report",
        })
        state["delivery_summary"]["stale_reports"] = 1
        output = dashboard.render_index([{
            "name": "demo", "description": "Demo", "workers": 0,
            "briefing": {}, "state": state, "delivery": state["delivery"],
        }])
        self.assertIn("stale report", output)
        self.assertIn("your-laptop", output)


if __name__ == "__main__":
    unittest.main()
