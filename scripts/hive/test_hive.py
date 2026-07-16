import unittest
from unittest.mock import patch, MagicMock
import json
import os
import sys
import tempfile
from pathlib import Path
import urllib.request

try:
    import hive
except ImportError:
    print("Error: hive.py not found — run tests from this directory.", file=sys.stderr)
    sys.exit(1)

# hive.py defines HiveDenyError and HiveConfigError; tests reference them via the
# module (hive.HiveDenyError) so the REAL classes are asserted — never shadow them here.


def create_mock_http_response(data, status=200):
    """Factory for a mock HTTPResponse suitable for urlopen()."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(data).encode('utf-8')
    mock_response.getcode.return_value = status
    mock_response.status = status
    mock_response.__enter__.return_value = mock_response
    return mock_response


class TestHiveContract(unittest.TestCase):
    """Contract tests for hive.py — no network calls."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_log_file = Path(self.temp_dir.name) / "runs.jsonl"
        self.run_log_patcher = patch('hive.RUN_LOG', self.temp_log_file)
        self.run_log_patcher.start()

    def tearDown(self):
        self.run_log_patcher.stop()
        self.temp_dir.cleanup()

    @patch('hive.HIVE_KEY', 'test-key')
    @patch('hive.urllib.request.urlopen')
    def test_ask_happy_path(self, mock_urlopen):
        mock_api_response = {
            "choices": [{"message": {"content": "This is a test response."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_urlopen.return_value = create_mock_http_response(mock_api_response)

        result = hive.gateway_chat("hive-fast", "test prompt")

        self.assertTrue(result['ok'])
        self.assertEqual(result['alias'], 'hive-fast')
        self.assertEqual(result['text'], 'This is a test response.')
        self.assertGreaterEqual(result['latency_ms'], 0)
        self.assertEqual(result['tokens_in'], 10)
        self.assertEqual(result['tokens_out'], 5)
        self.assertIsNone(result['error'])

        request_arg = mock_urlopen.call_args[0][0]
        self.assertIsInstance(request_arg, urllib.request.Request)
        self.assertEqual(request_arg.get_header('User-agent'), 'curl/8.6.0')
        self.assertEqual(request_arg.get_header('Authorization'), 'Bearer test-key')

    @patch('hive.urllib.request.urlopen')
    def test_swarm_preserves_order(self, mock_urlopen):
        def urlopen_side_effect(request, *args, **kwargs):
            model = json.loads(request.data).get('model')
            return create_mock_http_response(
                {"choices": [{"message": {"content": f"resp-{model}"}}]}
                if model in {"alias1", "alias2", "alias3"} else {}, 200 if model else 400
            )
        mock_urlopen.side_effect = urlopen_side_effect

        aliases = ['alias1', 'alias2', 'alias3']
        results = hive.swarm(aliases, "test prompt")

        self.assertEqual(len(results), 3)
        for alias, res in zip(aliases, results):
            self.assertEqual(res['alias'], alias)
            self.assertEqual(res['text'], f'resp-{alias}')
        self.assertEqual(mock_urlopen.call_count, 3)

    @patch('hive.gateway_chat')
    def test_check_verdict_pass_majority(self, mock_gateway_chat):
        mock_gateway_chat.side_effect = [
            {"ok": True, "text": "Generated output."},
            {"ok": True, "text": "VERDICT: PASS. This is correct."},
            {"ok": True, "text": "VERDICT: FAIL. This is wrong because..."},
            {"ok": True, "text": "VERDICT: PASS. Looks good to me."},
        ]
        result = hive.check("gen_alias", "some task")

        self.assertTrue(result['pass'])
        self.assertEqual(len(result['verdicts']), 3)
        self.assertEqual(result['verdicts'][0]['verdict'], 'PASS')
        self.assertEqual(result['verdicts'][1]['verdict'], 'FAIL')
        self.assertEqual(result['verdicts'][1]['critique'], 'This is wrong because...')
        self.assertEqual(result['verdicts'][2]['verdict'], 'PASS')

    @patch('hive.gateway_chat')
    def test_check_verdict_fail_on_missing_marker(self, mock_gateway_chat):
        mock_gateway_chat.side_effect = [
            {"ok": True, "text": "Generated output."},
            {"ok": True, "text": "VERDICT: PASS. This is correct."},
            {"ok": True, "text": "This response has no marker."},
            {"ok": True, "text": "VERDICT: FAIL. This is also wrong."},
        ]
        result = hive.check("gen_alias", "some task")

        self.assertFalse(result['pass'])
        self.assertEqual(result['verdicts'][1]['verdict'], 'FAIL')
        self.assertEqual(result['verdicts'][1]['critique'], 'This response has no marker.')

    @patch('hive.family_of', side_effect=lambda name: 'qwen' if 'qwen' in name else 'deepseek')
    @patch('hive.gateway_chat')
    def test_check_excludes_generator_family_judge(self, mock_gateway_chat, mock_family_of):
        gen_alias = "hive-coder-qwen"
        judges = ["judge-a-qwen", "judge-b-deepseek", "judge-c-deepseek"]
        mock_gateway_chat.side_effect = [
            {"ok": True, "text": "Generated code."},
            {"ok": True, "text": "VERDICT: PASS"},
            {"ok": True, "text": "VERDICT: PASS"},
        ]
        hive.check(gen_alias, "write code", judges=judges)

        called_aliases = [c.args[0] for c in mock_gateway_chat.call_args_list]
        self.assertIn(gen_alias, called_aliases)
        self.assertIn("judge-b-deepseek", called_aliases)
        self.assertIn("judge-c-deepseek", called_aliases)
        self.assertNotIn("judge-a-qwen", called_aliases)

    @patch('hive.family_of', side_effect=lambda name: 'qwen')
    @patch('hive.gateway_chat')
    def test_check_raises_if_too_few_judges_remain(self, mock_gateway_chat, mock_family_of):
        mock_gateway_chat.return_value = {"ok": True, "text": "Generated output."}

        with self.assertRaisesRegex(hive.HiveConfigError, "Not enough judges"):
            hive.check("gen-qwen", "task", judges=["judge-a-qwen", "judge-b-qwen"])

        mock_gateway_chat.assert_called_once()
        self.assertEqual(mock_gateway_chat.call_args.args[0], "gen-qwen")

    @patch('hive.gateway_chat')
    def test_check_short_circuits_on_failed_generation(self, mock_gateway_chat):
        mock_gateway_chat.return_value = {"ok": False, "text": "", "error": "timed out"}
        result = hive.check("gen_alias", "some task")
        self.assertFalse(result['pass'])
        self.assertEqual(result['verdicts'], [])
        mock_gateway_chat.assert_called_once()

    @patch('hive.urllib.request.urlopen')
    def test_deny_list_refuses_before_network(self, mock_urlopen):
        """A backend in DENY_CITATION is refused for citation/research tasks — no network call."""
        with patch('hive.DENY_CITATION', {"llama-3.3", "nemotron"}):
            with self.assertRaises(hive.HiveDenyError):
                hive.gateway_chat("some/llama-3.3-model", "Cite sources for this claim.", task_type="citation")
        mock_urlopen.assert_not_called()

    @patch('hive.urllib.request.urlopen')
    def test_deny_list_covers_pool_aliases(self, mock_urlopen):
        """Deny-list entries can name a POOL ALIAS directly (not just a raw model string) —
        e.g. if hive-fast's load-balanced pool includes a model you don't trust for
        citations, deny "hive-fast" itself rather than trying to deny each pool member."""
        with patch('hive.DENY_CITATION', {"hive-fast"}):
            with self.assertRaises(hive.HiveDenyError):
                hive.gateway_chat("hive-fast", "cite sources", task_type="citation")
        mock_urlopen.assert_not_called()

    def test_log_run_appends_valid_jsonl(self):
        self.assertFalse(os.path.exists(self.temp_log_file))

        record1 = {"ts": "2026-07-17T10:00:00Z", "cmd": "ask", "ok": True}
        hive.log_run(record1)
        with open(self.temp_log_file, "r") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), record1)

        record2 = {"ts": "2026-07-17T10:00:05Z", "cmd": "swarm", "ok": False}
        hive.log_run(record2)
        with open(self.temp_log_file, "r") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1]), record2)


if __name__ == "__main__":
    unittest.main()
