import json
import sys
import time
import types
import unittest

# The log module imports frappe; stand in for it only where it is absent (a
# bench has the real one). Everything tested here is pure -- the row is built
# without touching a database.
if "frappe" not in sys.modules:
    sys.modules["frappe"] = types.ModuleType("frappe")

from alaiy_os_connector_fulfillmen.fulfillmen.api_log import _row, context_for, safe_params

KEY = "271bd87a-60bd-4ef8-b3bc-5192e2e72de310000"


class Resp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class TestContext(unittest.TestCase):
    def test_context_from_the_path(self):
        self.assertEqual(context_for("/api-json/getinventorylist.aspx"), "inventory")
        self.assertEqual(context_for("/api-json/GetStorageList.aspx"), "storage_list")
        self.assertEqual(context_for("/api-json/GetTrackingInfo.aspx"), "tracking")

    def test_an_unmapped_path_is_other_not_a_crash(self):
        self.assertEqual(context_for("/api-json/SomethingNew.aspx"), "other")
        self.assertEqual(context_for(""), "other")
        self.assertEqual(context_for(None), "other")


class TestKeyNeverStored(unittest.TestCase):
    """The key is a query parameter on this API, so the log is the one place it
    could leak into the database. These are the tests that matter most here."""

    def test_params_drop_the_key(self):
        text = safe_params({"Key": KEY, "SKU": "A1", "page": 1}, KEY)
        self.assertNotIn(KEY, text)
        self.assertEqual(json.loads(text), {"SKU": "A1", "page": 1})

    def test_params_drop_the_key_whatever_its_case(self):
        self.assertNotIn(KEY, safe_params({"key": KEY}, KEY))
        self.assertNotIn(KEY, safe_params({"KEY": KEY}, KEY))

    def test_the_key_is_redacted_even_under_another_name(self):
        # Dropped by name first, then redacted by value, so a key that reached
        # the parameters some other way still cannot be written.
        self.assertNotIn(KEY, safe_params({"SKU": KEY}, KEY))

    def test_no_part_of_the_row_carries_the_key(self):
        # An echo of the request URL in the body is exactly how a key reaches a
        # log table, so the excerpt and the message are redacted too.
        row = _row(
            "/api-json/getinventorylist.aspx",
            {"Key": KEY, "SKU": "A1"},
            KEY,
            time.monotonic(),
            resp=Resp(200, f'{{"Code":"108","Enmessage":"fails for Key={KEY}"}}'),
            data={"Code": "108", "Enmessage": f"fails for Key={KEY}"},
        )
        self.assertNotIn(KEY, json.dumps(row))


class TestOutcome(unittest.TestCase):
    def test_a_200_carrying_a_bad_code_is_a_failure(self):
        row = _row("/api-json/getinventorylist.aspx", {}, KEY, time.monotonic(),
                   resp=Resp(200, "{}"), data={"Code": "108", "Enmessage": "fails"})
        self.assertEqual(row["outcome"], "Failed")
        self.assertEqual(row["api_code"], "108")
        self.assertEqual(row["api_message"], "fails")
        self.assertEqual(row["status_code"], 200)

    def test_code_100_is_a_success(self):
        row = _row("/api-json/getinventorylist.aspx", {}, KEY, time.monotonic(),
                   resp=Resp(200, "{}"), data={"Code": "100", "data": []})
        self.assertEqual(row["outcome"], "Success")
        self.assertEqual(row["api_code"], "100")

    def test_a_call_that_never_returned(self):
        row = _row("/api-json/getinventorylist.aspx", {}, KEY, time.monotonic(),
                   error=ValueError("connection reset"))
        self.assertEqual(row["outcome"], "Failed")
        self.assertEqual(row["status_code"], 0)
        self.assertIn("connection reset", row["api_message"])

    def test_a_non_200_is_a_failure_even_with_no_envelope(self):
        row = _row("/api-json/getinventorylist.aspx", {}, KEY, time.monotonic(), resp=Resp(403, "nope"))
        self.assertEqual(row["outcome"], "Failed")
        self.assertEqual(row["status_code"], 403)

    def test_the_excerpt_is_bounded(self):
        row = _row("/api-json/getinventorylist.aspx", {}, KEY, time.monotonic(),
                   resp=Resp(200, "x" * 20000), data={"Code": "100"})
        self.assertLessEqual(len(row["response_excerpt"]), 4000)


if __name__ == "__main__":
    unittest.main()
