import unittest

from alaiy_os_connector_fulfillmen.fulfillmen.util import (
    ASN_STATUS,
    ORDER_STATUS,
    POLLED_ASN_STATUSES,
    POLLED_ORDER_STATUSES,
    TERMINAL_ASN_STATUSES,
    TRACKING_DONE,
    TRACKING_STATUS,
    clean,
    events_text,
    redact,
    split_across,
    to_datetime,
    to_number,
    verify_webhook,
)


class TestUtil(unittest.TestCase):
    def test_redact_removes_key_in_every_form(self):
        key = "ab/cd+ef 12"
        for form in (key, "ab%2Fcd%2Bef%2012", "ab%2Fcd%2Bef+12"):
            self.assertNotIn("cd", redact(f"GET /x?Key={form}&page=1", key).replace("cd=", ""))
        self.assertEqual(redact("plain", None, ""), "plain")

    def test_clean(self):
        self.assertEqual(clean("6925925700115 "), "6925925700115")
        self.assertEqual(clean(None), "")
        self.assertEqual(clean(12), "12")

    def test_to_datetime(self):
        self.assertEqual(to_datetime("2026/10/12 10:00:00"), "2026-10-12 10:00:00")
        self.assertEqual(to_datetime("2020/4/8 7:27:37"), "2020-04-08 07:27:37")
        self.assertEqual(to_datetime("2026-10-12"), "2026-10-12 00:00:00")
        self.assertEqual(to_datetime("2026-10-12T10:00"), "2026-10-12 10:00:00")
        for bad in ("", None, "   ", "n/a", "2026-13-01 00:00:00", "2026-10-12 25:00:00"):
            self.assertIsNone(to_datetime(bad))

    def test_to_number(self):
        self.assertEqual(to_number("20"), 20)
        self.assertEqual(to_number("2.5"), 2.5)
        self.assertEqual(to_number(""), 0)
        self.assertEqual(to_number(None), 0)
        self.assertEqual(to_number("x", default=None), None)

    def test_split_across(self):
        self.assertEqual(split_across(15, [10, 10]), [10, 5])
        self.assertEqual(split_across(25, [10, 10]), [10, 15])   # remainder on last
        self.assertEqual(split_across(0, [10, 10]), [0, 0])
        self.assertEqual(split_across(7, [10]), [7])

    def test_verify_webhook(self):
        h = {"App-Key": "k", "Access-Token": "t", "X-Customer-Code": "C1"}
        self.assertTrue(verify_webhook(h, "k", "t", "C1"))
        self.assertTrue(verify_webhook(h, "k"))
        self.assertFalse(verify_webhook(h, "other"))
        self.assertFalse(verify_webhook(h, "k", "wrong"))
        self.assertFalse(verify_webhook(h, "k", None, "C2"))
        self.assertFalse(verify_webhook({}, "k"))
        self.assertFalse(verify_webhook(h, ""))     # unconfigured secret never matches

    def test_status_tables_are_consistent(self):
        # every polled status has a label; polled and terminal never overlap
        for code in POLLED_ASN_STATUSES + list(TERMINAL_ASN_STATUSES):
            self.assertIn(code, ASN_STATUS)
        self.assertFalse(set(POLLED_ASN_STATUSES) & TERMINAL_ASN_STATUSES)
        for code in POLLED_ORDER_STATUSES + ["6", "8"]:
            self.assertIn(code, ORDER_STATUS)
        self.assertTrue(TRACKING_DONE <= set(TRACKING_STATUS))

    def test_events_text(self):
        events = [{"OccurTime": "2026-01-01 10:00:00", "DetailDesc": "a"}, {"OccurTime": "2026-01-01 11:00:00", "DetailDesc": "b"}]
        self.assertEqual(events_text(events), "2026-01-01 10:00:00  a\n2026-01-01 11:00:00  b")
        self.assertEqual(events_text([]), "")
        self.assertEqual(events_text(None), "")


if __name__ == "__main__":
    unittest.main()
