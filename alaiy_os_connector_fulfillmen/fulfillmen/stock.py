# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Warehouse stock. Reads Fulfillmen inventory and stores the totals on the Item
whose item_code equals the SKU. Read only; no document is created.

  GET /api-json/getinventorylist.aspx   (filters: Storage, SKU, page; 20 rows per page)

  TotalNumber  available stock -> fulfillmen_available_stock
  Number       shelf stock     -> fulfillmen_shelf_stock

A SKU held in several warehouses is summed, unless a Warehouse Code is set in
the settings, in which case only that warehouse is read. The webhook for a
product change re-reads just that SKU, so the stock value comes from the
inventory call, never from the notification text.

A SKU that drops out of the inventory list (stock gone) is set to 0 on the next
full read, but only when that read returned at least one row, so an empty or
wrongly scoped response never wipes every Item.

Item fields are plain information (no document event depends on them), so they
are written with set_value and update_modified=False to keep Item "modified"
meaningful for real edits.
"""

import frappe
from frappe.utils import now_datetime

from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenClient
from alaiy_os_connector_fulfillmen.fulfillmen.common import new_result
from alaiy_os_connector_fulfillmen.fulfillmen.util import clean, to_number

INVENTORY_PATH = "/api-json/getinventorylist.aspx"
PAGE_SIZE = 20   # fixed by the API
_FIELDS = ["fulfillmen_available_stock", "fulfillmen_shelf_stock"]


def _totals(rows):
    """{sku: [available, shelf]} summed over the rows."""
    totals = {}
    for row in rows:
        sku = clean(row.get("SKU"))
        if not sku:
            continue
        t = totals.setdefault(sku, [0, 0])
        t[0] += to_number(row.get("TotalNumber"))
        t[1] += to_number(row.get("Number"))
    return totals


def _write(sku, available, shelf, result):
    current = frappe.db.get_value("Item", sku, _FIELDS, as_dict=True)
    if (to_number(current.fulfillmen_available_stock), to_number(current.fulfillmen_shelf_stock)) == (available, shelf):
        return
    try:
        frappe.db.set_value(
            "Item", sku,
            {
                "fulfillmen_available_stock": available,
                "fulfillmen_shelf_stock": shelf,
                "fulfillmen_stock_synced_at": now_datetime(),
            },
            update_modified=False,
        )
        result["updated"] += 1
    except Exception:
        result["failed"] += 1
        frappe.log_error(title=f"Fulfillmen stock update failed: {sku}", message=frappe.get_traceback())


def apply_totals(totals, result):
    for sku, (available, shelf) in totals.items():
        result["processed"] += 1
        if not frappe.db.exists("Item", sku):
            result["unmatched"] += 1
            continue
        _write(sku, available, shelf, result)


def sync_stock():
    client = FulfillmenClient()
    result = new_result()
    totals = _totals(client.pages(INVENTORY_PATH, "page", PAGE_SIZE, Storage=client.storage))
    apply_totals(totals, result)

    if totals:
        # Items we stored stock for earlier that are no longer listed: now zero.
        stale = frappe.get_all(
            "Item",
            filters={"fulfillmen_stock_synced_at": ["is", "set"], "name": ["not in", list(totals)]},
            fields=["name", *_FIELDS],
        )
        for item in stale:
            if to_number(item.fulfillmen_available_stock) or to_number(item.fulfillmen_shelf_stock):
                result["processed"] += 1
                _write(item.name, 0, 0, result)
    else:
        result["notes"].append("Inventory returned no rows; existing Item values were left as they are.")

    if result["unmatched"]:
        result["notes"].append(f"{result['unmatched']} SKU(s) have no Item with that item code.")
    frappe.db.commit()
    return result


def refresh_sku(sku):
    """Targeted re-pull for one SKU (webhook). SKU is a filter on the API, so
    only rows for exactly this SKU are kept; no rows means it is out of stock."""
    client = FulfillmenClient()
    result = new_result()
    rows = [r for r in client.pages(INVENTORY_PATH, "page", PAGE_SIZE, Storage=client.storage, SKU=sku)
            if clean(r.get("SKU")) == sku]
    apply_totals(_totals(rows) or {sku: [0, 0]}, result)
    frappe.db.commit()
    return result
