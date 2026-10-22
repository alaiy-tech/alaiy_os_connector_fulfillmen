# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Warehouse stock. Everything that reads Fulfillmen inventory lives here, so the
endpoint's path, its page size and the meaning of its two quantities are
written down once:

  * the sweep (`sync_stock`, `refresh_sku`) walks every page and stores the
    totals on the Item whose item_code equals the SKU;
  * `read_page` answers a single page to whoever is asking now, and writes
    nothing.

Read only; no document is created.

  GET /api-json/getinventorylist.aspx   (filters: Storage, SKU, page; 20 rows per page)
  GET /api-json/GetStorageList.aspx     (the warehouse codes that scope the above)

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
from alaiy_os_connector_fulfillmen.fulfillmen.util import clean, inventory_row, to_number

INVENTORY_PATH = "/api-json/getinventorylist.aspx"
STORAGE_PATH = "/api-json/GetStorageList.aspx"
PAGE_SIZE = 20   # fixed by the API
_FIELDS = ["fulfillmen_available_stock", "fulfillmen_shelf_stock"]


def _totals(rows):
    """{sku: [available, shelf]} summed over the rows."""
    totals = {}
    for raw in rows:
        row = inventory_row(raw)
        if not row["sku"]:
            continue
        t = totals.setdefault(row["sku"], [0, 0])
        t[0] += row["available"]
        t[1] += row["on_hand"]
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


def read_page(sku=None, storage=None, page=1):
    """One page of the inventory list, unaggregated and written nowhere.

    The same endpoint, client and page size as the sweep above, asked a
    narrower question: what does the warehouse say right now. Nothing touches
    an Item, so this answers for SKUs that have no Item at all -- which the
    sweep counts as unmatched and drops.

    `storage` falls back to the configured Warehouse Code, so a caller and the
    sweep cannot end up scoped differently by accident. Without either, the
    read spans every warehouse the account can see and the response carries no
    warehouse field, so a SKU held in two of them is two rows that cannot be
    told apart. They are returned as they came rather than summed the way
    `_totals` sums them: that is safe over every page and wrong over one, where
    it would add up halves of two different pages.

    `has_more` is a full page rather than the response's `count` -- the docs
    call that a total without guaranteeing it, which is why `pages()` ignores
    it too. A catalogue that is an exact multiple of the page size therefore
    offers one empty last page, the harmless direction to be wrong in.

    Raises FulfillmenAPIError, like every other call here.
    """
    client = FulfillmenClient()
    warehouse = clean(storage) or client.storage
    raw = client.get(
        INVENTORY_PATH,
        page=page,
        Storage=warehouse,
        SKU=clean(sku) or None,
    ).get("data") or []

    rows = [row for row in (inventory_row(r) for r in raw) if row["sku"]]
    return {"rows": rows, "warehouse": warehouse or None, "has_more": len(raw) >= PAGE_SIZE}


def warehouse_codes():
    """The warehouse codes this account can see.

    The cheapest read that needs nothing but the API key, which is why the
    connection test uses it as its key check too. A warehouse code is what
    scopes every stock read, so the list of them belongs here with them.

    Raises FulfillmenAPIError.
    """
    rows = FulfillmenClient().get(STORAGE_PATH).get("data") or []
    return [code for code in (clean(r.get("ShortName")) for r in rows) if code]
