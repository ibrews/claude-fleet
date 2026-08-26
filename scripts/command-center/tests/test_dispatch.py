import os
import sys
import tempfile
import unittest


LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, os.path.abspath(LIB))
import dispatch  # noqa: E402
import guardrail  # noqa: E402
import work_items  # noqa: E402


class DispatchTicketTests(unittest.TestCase):
    def test_generated_trigger_satisfies_v1_contract(self):
        policy = guardrail.load_policy(os.path.join(LIB, "..", "policy.json"))
        with tempfile.TemporaryDirectory() as directory:
            classification, path, _ = dispatch.create_trigger(
                directory,
                trigger_id="generated-2026-08-26",
                target="alpha",
                title="Verify generated ticket",
                task="Exercise the provider-neutral dispatch path.",
                done_criteria="The generated ticket passes work-item validation.",
                verification="Parse the generated file and assert no schema issues.",
                instance="demo",
                policy=policy,
            )
            self.assertEqual(classification, guardrail.GREEN)
            self.assertEqual(work_items.parse_trigger(path)["schema_issues"], [])


if __name__ == "__main__":
    unittest.main()
