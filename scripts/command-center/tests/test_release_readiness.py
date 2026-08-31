import os
import sys
import unittest


LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, os.path.abspath(LIB))
import release_readiness  # noqa: E402


class ReleaseReadinessTests(unittest.TestCase):
    def manifest(self, target="external_pilot", status="pass"):
        gates = {}
        for stage in release_readiness.TARGET_STAGES[target]:
            gates[stage] = [{"id": f"{stage}-check", "status": status, "evidence": "artifact"}]
        return {"schema": release_readiness.SCHEMA, "product": "Demo",
                "release_target": target, "gates": gates}

    def test_external_pilot_requires_human_portability_and_packaging_gates(self):
        result = release_readiness.evaluate(self.manifest())
        self.assertTrue(result["ready"])
        self.assertIn("human_usable", result["stage_results"])
        self.assertIn("packaging", result["stage_results"])

    def test_unknown_gate_blocks_readiness(self):
        manifest = self.manifest()
        manifest["gates"]["reproducible"][0]["status"] = "unknown"
        result = release_readiness.evaluate(manifest)
        self.assertFalse(result["ready"])
        self.assertIn("reproducible", result["blockers"])

    def test_pass_without_evidence_is_invalid(self):
        manifest = self.manifest("internal_demo")
        manifest["gates"]["visual"][0]["evidence"] = ""
        result = release_readiness.evaluate(manifest)
        self.assertFalse(result["ready"])
        self.assertTrue(any("pass requires evidence" in issue for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
