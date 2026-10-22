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

A warehouse is mandatory for the inventory call (without `Storage` it answers
code 108). A SKU held in several warehouses is summed. With a Warehouse Code set
in the settings only that warehouse is read; without one every warehouse of the
account is read, one after the other, from the warehouse list.

The inventory call reports an empty page, a warehouse with no stock and a SKU
with no stock as code 105 ("no inventory") instead of an empty list, and it
returns every row on page 1 whatever the documented page size. So it is read
until a page is empty, comes back as 105, or adds no new row (see
`util.collect_pages`); 105 is "no rows" here and nothing else. The webhook for a
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

from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenAPIError, FulfillmenClient
from alaiy_os_connector_fulfillmen.fulfillmen.common import new_result
from alaiy_os_connector_fulfillmen.fulfillmen.util import clean, collect_pages, inventory_row, to_number

INVENTORY_PATH = "/api-json/getinventorylist.aspx"
STORAGE_PATH = "/api-json/GetStorageList.aspx"
PAGE_SIZE = 20   # the documented size; the API does not hold to it (see the module docstring)
NO_STOCK_CODE = "105"   # the API's way of saying "no rows"
_FIELDS = ["fulfillmen_available_stock", "fulfillmen_shelf_stock"]


def _fetch(client, page, **filters):
    """One page of rows. Code 105 is an empty answer, not an error."""
    try:
        return client.get(INVENTORY_PATH, page=page, **filters).get("data") or []
    except FulfillmenAPIError as e:
        if e.api_code == NO_STOCK_CODE:
            return []
        raise


def _row_key(row):
    return (clean(row.get("GoodsID")), clean(row.get("SKU")), clean(row.get("GoodsCode")))


def _codes(client, storage=None):
    """The warehouse codes to read: the one asked for, else the one in the
    settings, else every warehouse of the account."""
    chosen = clean(storage) or client.storage
    if chosen:
        return [chosen]
    rows = client.get(STORAGE_PATH).get("data") or []
    return [code for code in (clean(r.get("ShortName")) for r in rows) if code]


def _inventory(client, code, sku=None):
    """Every inventory row of one warehouse (optionally one SKU)."""
    return collect_pages(
        lambda page: _fetch(client, page, Storage=code, SKU=sku or None), _row_key
    )


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
    codes = _codes(client)
    rows = [row for code in codes for row in _inventory(client, code)]
    totals = _totals(rows)
    result["notes"].append(f"Read {len(codes)} warehouse(s): {', '.join(codes) or 'none'}.")
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
    rows = [r for code in _codes(client) for r in _inventory(client, code, sku)
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

    The warehouse is mandatory at Fulfillmen, so with none given and none in the
    settings, page `page` of every warehouse is read and each row says which
    warehouse it is from (`warehouse`), so a SKU held in two of them is two rows
    that can be told apart.

    `has_more` is a full page rather than the response's `count` -- the docs
    call that a total without guaranteeing it. The API may return more rows than
    the documented page size, so a page after the last can be asked for: it comes
    back as code 105, which is read as an empty page and ends the list.

    Raises FulfillmenAPIError, like every other call here, except for code 105.
    """
    client = FulfillmenClient()
    codes = _codes(client, storage)
    rows, more = [], False
    for code in codes:
        raw = _fetch(client, page, Storage=code, SKU=clean(sku) or None)
        more = more or len(raw) >= PAGE_SIZE
        rows.extend({**row, "warehouse": code} for row in (inventory_row(r) for r in raw) if row["sku"])
    return {
        "rows": rows,
        "warehouse": codes[0] if len(codes) == 1 else None,
        "has_more": more,
    }


def warehouse_codes():
    """The warehouse codes this account can see.

    The cheapest read that needs nothing but the API key, which is why the
    connection test uses it as its key check too. A warehouse code is what
    scopes every stock read, so the list of them belongs here with them.

    Raises FulfillmenAPIError.
    """
    rows = FulfillmenClient().get(STORAGE_PATH).get("data") or []
    return [code for code in (clean(r.get("ShortName")) for r in rows) if code]
