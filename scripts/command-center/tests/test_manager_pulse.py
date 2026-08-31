import os
import sys
import time
import unittest


ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(ROOT))
import manager_pulse  # noqa: E402


class ManagerPulseTests(unittest.TestCase):
    def snapshot(self, reasons, fingerprint="new"):
        return {"reasons": reasons, "fingerprint": fingerprint}

    def test_healthy_tick_never_wakes_manager(self):
        send, _ = manager_pulse.should_nudge(self.snapshot([]), {})
        self.assertFalse(send)

    def test_state_transition_wakes_manager_once(self):
        send, _ = manager_pulse.should_nudge(self.snapshot(["task changed"]), {"fingerprint": "old"})
        self.assertTrue(send)
        send, _ = manager_pulse.should_nudge(
            self.snapshot(["task changed"]),
            {"fingerprint": "new", "last_nudge_epoch": int(time.time())},
        )
        self.assertFalse(send)

    def test_unanswered_nudge_retries_after_cooldown(self):
        send, _ = manager_pulse.should_nudge(
            self.snapshot(["still stale"]),
            {"fingerprint": "new", "last_nudge_epoch": int(time.time()) - 3700},
            retry_minutes=60,
        )
        self.assertTrue(send)


if __name__ == "__main__":
    unittest.main()
