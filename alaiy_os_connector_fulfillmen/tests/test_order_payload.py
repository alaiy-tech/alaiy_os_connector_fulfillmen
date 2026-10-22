import unittest

from alaiy_os_connector_fulfillmen.fulfillmen.order_payload import (
    STATUS_CONFIRMED,
    STATUS_DRAFT,
    build_create_payload,
)

DEFAULTS = {
    "customer_id": "10000", "shipping_code": "MZL", "style": "1",
    "warehouse_code": "USW", "status": STATUS_DRAFT,
}


def order(**over):
    base = {
        "reference_no": "REF-1",
        "ship_to": {"name": "Rob", "country": "US", "state": "NJ", "city": "Hoboken", "address1": "1 Main St"},
        "items": [{"sku": "S1", "quantity": 2, "weight": 0.5, "price": 10, "currency": "usd"}],
    }
    base.update(over)
    return base


class TestCreatePayload(unittest.TestCase):
    def test_minimal_order_maps_to_api_names(self):
        p = build_create_payload(order(), DEFAULTS)
        self.assertEqual(p["Style"], "1")
        self.assertEqual(p["CustomerID"], "10000")
        self.assertEqual(p["ShippingCode"], "MZL")
        self.assertEqual(p["WarehouseId"], "USW")
        self.assertEqual(p["OrderStatus"], STATUS_DRAFT)
        self.assertEqual(p["CsRefNo"], "REF-1")
        self.assertEqual(p["ShipToAdress1"], "1 Main St")
        self.assertEqual(p["Products"], [{"SKU": "S1", "Quantity": 2, "Weight": 0.5, "Price": 10.0, "Currency": "USD"}])

    def test_optional_fields_are_left_out_when_empty(self):
        p = build_create_payload(order(), DEFAULTS)
        for key in ("ShipToEmail", "ShipToPhoneNumber", "TrackingNo", "CusRemark", "CustWeight"):
            self.assertNotIn(key, p)
        p = build_create_payload(order(remark="fragile", weight=2.5), DEFAULTS)
        self.assertEqual((p["CusRemark"], p["CustWeight"]), ("fragile", "2.5"))

    def test_confirmed_status_and_ordinary_style(self):
        p = build_create_payload(order(), {**DEFAULTS, "status": STATUS_CONFIRMED, "style": "2"})
        self.assertEqual(p["OrderStatus"], STATUS_CONFIRMED)
        self.assertNotIn("WarehouseId", p)

    def test_order_shipping_code_beats_default(self):
        self.assertEqual(build_create_payload(order(shipping_code="UPS"), DEFAULTS)["ShippingCode"], "UPS")

    def test_every_problem_is_reported_together(self):
        with self.assertRaises(ValueError) as ctx:
            build_create_payload({"ship_to": {}, "items": [{"sku": "", "quantity": 1.5, "weight": 0, "price": -1, "currency": "INR"}]},
                                 {"style": "1"})
        msg = str(ctx.exception)
        for part in ("customer_id", "reference_no", "shipping_code", "warehouse_code", "ship_to.name", "ship_to.country",
                     "ship_to.state", "ship_to.city", "ship_to.address1", "items[1].sku", "items[1].quantity",
                     "items[1].weight", "items[1].price", "items[1].currency"):
            self.assertIn(part, msg)

    def test_items_must_be_a_list_with_content(self):
        for items in (None, [], "x"):
            with self.assertRaises(ValueError):
                build_create_payload(order(items=items), DEFAULTS)

    def test_length_limits(self):
        long_name = "x" * 101
        with self.assertRaises(ValueError) as ctx:
            build_create_payload(order(ship_to={**order()["ship_to"], "name": long_name}), DEFAULTS)
        self.assertIn("ship_to.name is longer than 100", str(ctx.exception))

    def test_bad_style(self):
        with self.assertRaises(ValueError):
            build_create_payload(order(), {**DEFAULTS, "style": "3"})


if __name__ == "__main__":
    unittest.main()
