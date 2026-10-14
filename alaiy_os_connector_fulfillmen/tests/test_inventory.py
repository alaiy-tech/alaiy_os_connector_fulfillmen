import sys
import types
import unittest

# The endpoint module imports frappe; stand in for it only where it is absent
# (a bench has the real one). The helper under test is pure.
if "frappe" not in sys.modules:
    stub = types.ModuleType("frappe")
    stub.whitelist = lambda *a, **k: (lambda fn: fn)
    sys.modules["frappe"] = stub

from alaiy_os_connector_fulfillmen.api.inventory import _row


class TestInventoryRow(unittest.TestCase):
    def test_row_maps_the_documented_fields(self):
        self.assertEqual(
            _row(
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

    def test_missing_quantities_are_zero_not_none(self):
        # The API returns numbers as strings and omits them when empty; a blank
        # is no stock, and the table has to render something.
        self.assertEqual(_row({"SKU": "A"}), {"sku": "A", "barcode": "", "available": 0, "on_hand": 0})
        self.assertEqual(_row({"SKU": "A", "TotalNumber": "", "Number": None})["available"], 0)

    def test_available_and_shelf_are_kept_apart(self):
        # TotalNumber is sellable and Number is on the shelf; they differ by
        # what is allocated but not yet picked, so neither stands in for the
        # other.
        row = _row({"SKU": "A", "TotalNumber": "3", "Number": "10"})
        self.assertEqual((row["available"], row["on_hand"]), (3, 10))


if __name__ == "__main__":
    unittest.main()
