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
    collect_pages,
    events_text,
    inventory_row,
    redact,
    split_across,
    to_datetime,
    to_number,
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

    def test_inventory_row(self):
        self.assertEqual(
            inventory_row(
                {
                    "SKU": "20190402001 ",
                    "GoodsCode": "6925925700115",
                    "TotalNumber": "7",
                    "Number": "5",
                    "temprownumber": "1",
                }
            ),
            {"sku": "20190402001", "barcode": "6925925700115", "available": 7, "on_hand": 5},
        )
        # Omitted or empty quantities are no stock, not an absent figure: the
        # sweep adds these up and a screen has to render something.
        self.assertEqual(
            inventory_row({"SKU": "A"}), {"sku": "A", "barcode": "", "available": 0, "on_hand": 0}
        )
        self.assertEqual(inventory_row({"SKU": "A", "TotalNumber": "", "Number": None})["available"], 0)
        # Sellable and on-shelf differ by what is allocated but not yet picked,
        # so neither stands in for the other.
        row = inventory_row({"SKU": "A", "TotalNumber": "3", "Number": "10"})
        self.assertEqual((row["available"], row["on_hand"]), (3, 10))

    def test_split_across(self):
        self.assertEqual(split_across(15, [10, 10]), [10, 5])
        self.assertEqual(split_across(25, [10, 10]), [10, 15])   # remainder on last
        self.assertEqual(split_across(0, [10, 10]), [0, 0])
        self.assertEqual(split_across(7, [10]), [7])

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


class TestCollectPages(unittest.TestCase):
    @staticmethod
    def key(row):
        return row["id"]

    def test_stops_at_the_first_empty_page(self):
        pages = {1: [{"id": 1}, {"id": 2}], 2: [{"id": 3}], 3: []}
        calls = []

        def fetch(page):
            calls.append(page)
            return pages.get(page, [])

        self.assertEqual([r["id"] for r in collect_pages(fetch, self.key)], [1, 2, 3])
        self.assertEqual(calls, [1, 2, 3])

    def test_one_big_first_page_is_not_followed_by_a_guess(self):
        # The inventory call returns every row on page 1 (38 here, documented size
        # 20): reading must not depend on a page being shorter than a stated size.
        big = [{"id": i} for i in range(38)]
        calls = []

        def fetch(page):
            calls.append(page)
            return big if page == 1 else []

        self.assertEqual(len(collect_pages(fetch, self.key)), 38)
        self.assertEqual(calls, [1, 2])

    def test_a_page_that_adds_nothing_new_ends_the_read(self):
        # A server that ignores the page number and repeats page 1 must not loop.
        rows = [{"id": 1}, {"id": 2}]
        calls = []

        def fetch(page):
            calls.append(page)
            return rows

        self.assertEqual(len(collect_pages(fetch, self.key)), 2)
        self.assertEqual(calls, [1, 2])

    def test_duplicates_across_pages_are_dropped_and_new_rows_kept(self):
        pages = {1: [{"id": 1}, {"id": 2}], 2: [{"id": 2}, {"id": 3}], 3: []}
        self.assertEqual([r["id"] for r in collect_pages(lambda p: pages.get(p, []), self.key)], [1, 2, 3])

    def test_no_rows_at_all(self):
        self.assertEqual(collect_pages(lambda page: [], self.key), [])

    def test_safety_stop(self):
        n = iter(range(10 ** 6))
        self.assertEqual(len(collect_pages(lambda page: [{"id": next(n)}], self.key, max_pages=7)), 7)


if __name__ == "__main__":
    unittest.main()
