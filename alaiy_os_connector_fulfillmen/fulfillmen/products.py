# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Product registration. Reads the products registered at Fulfillmen and stores,
on the Item whose item_code equals the SKU, whether Fulfillmen knows it and what
the warehouse measured at QC. Read only; ERPNext stays the product master.

  GET /api-json/GetGoodsList.aspx   (filters: SKU, Barcode, Page; 50 rows per page)

  (row present)  -> fulfillmen_registered = 1
  Barcode        -> fulfillmen_barcode
  CheckWeight    -> fulfillmen_qc_weight
  CheckLength    -> fulfillmen_qc_length
  CheckWidth     -> fulfillmen_qc_width
  CheckHeight    -> fulfillmen_qc_height

The QC measurements are empty until the warehouse has inspected the product.
An Item stored as registered that drops out of the list is set back to not
registered, but only when the read returned at least one row.
"""

import frappe

from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenClient
from alaiy_os_connector_fulfillmen.fulfillmen.common import new_result, put
from alaiy_os_connector_fulfillmen.fulfillmen.util import clean, to_number

PRODUCT_PATH = "/api-json/GetGoodsList.aspx"
PAGE_SIZE = 50   # fixed by the API

_NUMBERS = (
    ("CheckWeight", "fulfillmen_qc_weight"),
    ("CheckLength", "fulfillmen_qc_length"),
    ("CheckWidth", "fulfillmen_qc_width"),
    ("CheckHeight", "fulfillmen_qc_height"),
)


def _write(sku, values, result):
    current = frappe.db.get_value("Item", sku, list(values), as_dict=True)
    changed = {f: v for f, v in values.items() if (current.get(f) or 0) != (v or 0) or (current.get(f) or "") != (v or "")}
    if not changed:
        return
    try:
        frappe.db.set_value("Item", sku, changed, update_modified=False)
        result["updated"] += 1
    except Exception:
        result["failed"] += 1
        frappe.log_error(title=f"Fulfillmen product update failed: {sku}", message=frappe.get_traceback())


def apply_products(rows, result):
    """Returns the set of SKUs seen."""
    seen = set()
    for row in rows:
        sku = clean(row.get("SKU"))
        if not sku:
            continue
        seen.add(sku)
        result["processed"] += 1
        if not frappe.db.exists("Item", sku):
            result["unmatched"] += 1
            continue
        values = {"fulfillmen_registered": 1, "fulfillmen_barcode": clean(row.get("Barcode"))}
        for api_field, item_field in _NUMBERS:
            values[item_field] = to_number(row.get(api_field))
        _write(sku, values, result)
    return seen


def sync_products():
    client = FulfillmenClient()
    result = new_result()
    seen = apply_products(client.pages(PRODUCT_PATH, "Page", PAGE_SIZE), result)

    if seen:
        gone = frappe.get_all("Item", filters={"fulfillmen_registered": 1, "name": ["not in", list(seen)]}, pluck="name")
        for sku in gone:
            result["processed"] += 1
            _write(sku, {"fulfillmen_registered": 0}, result)
    else:
        result["notes"].append("Product list returned no rows; existing Item values were left as they are.")

    if result["unmatched"]:
        result["notes"].append(f"{result['unmatched']} registered product(s) have no Item with that item code.")
    frappe.db.commit()
    return result
