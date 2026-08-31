import json
import os
import sys
import tempfile
import unittest


LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, os.path.abspath(LIB))
import session_health  # noqa: E402


class SessionHealthTests(unittest.TestCase):
    def write_transcript(self, usage):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        handle.write(json.dumps({
            "type": "assistant", "sessionId": "demo-session", "effort": "high",
            "timestamp": "2026-08-31T00:00:00Z",
            "message": {"model": "claude-opus", "usage": usage},
        }) + "\n")
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def test_context_estimate_sums_prompt_cache_footprint(self):
        path = self.write_transcript({
            "input_tokens": 2, "cache_read_input_tokens": 430000,
            "cache_creation_input_tokens": 90000,
        })
        result = session_health.inspect_transcript(path)
        self.assertEqual(result["context_tokens"], 520002)
        self.assertEqual(result["status"], "rollover")
        self.assertEqual(result["model"], "claude-opus")

    def test_small_context_is_healthy(self):
        path = self.write_transcript({"input_tokens": 1000})
        self.assertEqual(session_health.inspect_transcript(path)["status"], "healthy")

    def test_fleet_alias_resolves_embedded_uuid_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            project = os.path.join(root, "project")
            os.makedirs(project)
            path = os.path.join(project, "4800e94c-15da-4410-bca4-9154d9288016.jsonl")
            with open(path, "w") as handle:
                handle.write("{}\n")
            self.assertEqual(
                session_health.find_transcript(root, "knowledge-4800e94c-primary"), path,
            )


if __name__ == "__main__":
    unittest.main()
