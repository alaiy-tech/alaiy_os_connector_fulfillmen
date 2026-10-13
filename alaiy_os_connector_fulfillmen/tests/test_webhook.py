import sys
import types
import unittest

# The endpoint module imports frappe; stand in for it only where it is absent
# (a bench has the real one). The helper under test is pure.
if "frappe" not in sys.modules:
    stub = types.ModuleType("frappe")
    stub.whitelist = lambda *a, **k: (lambda fn: fn)
    sys.modules["frappe"] = stub

from alaiy_os_connector_fulfillmen.api.webhook import _verified


class TestWebhookAuth(unittest.TestCase):
    def test_verified(self):
        h = {"App-Key": "k", "Access-Token": "t", "X-Customer-Code": "C1"}
        self.assertTrue(_verified(h, "k", "t", "C1"))
        self.assertTrue(_verified(h, "k"))
        self.assertFalse(_verified(h, "other"))
        self.assertFalse(_verified(h, "k", "wrong"))
        self.assertFalse(_verified(h, "k", None, "C2"))
        self.assertFalse(_verified({}, "k"))
        self.assertFalse(_verified(h, ""))      # unconfigured secret never matches
        self.assertFalse(_verified(h, None))


if __name__ == "__main__":
    unittest.main()
