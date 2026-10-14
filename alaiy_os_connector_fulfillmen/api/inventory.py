# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
On-demand inventory reads, for a screen someone is looking at.

Separate from `fulfillmen/stock.py`, which is the scheduled sweep: that one
walks every page and writes totals onto Item, so what it leaves behind is as
old as the last run. This answers one page at a time, straight from the
warehouse, so a screen built on it shows what Fulfillmen says now.

  GET /api-json/getinventorylist.aspx   (filters: Storage, SKU, page)
  GET /api-json/GetStorageList.aspx     (the warehouse picker's options)

Only `Key` is required by the API; Storage and SKU are filters and page
defaults to the first. The key is a URL query parameter at Fulfillmen, so this
call can only ever be made from the backend -- a browser making it directly
would put the key in a URL the person can read.

Failures are returned, never raised. An empty table and an unreachable
warehouse are different answers, and a screen that cannot tell them apart
reports "no stock" for an outage.
"""

import frappe

# util is pure; the client and the sweep both reach for `requests`, so they are
# imported inside the endpoints the way test_connection.py does. That keeps this
# module importable -- and its row mapping testable -- without the HTTP stack.
from alaiy_os_connector_fulfillmen.fulfillmen.util import clean, to_number

STORAGE_PATH = "/api-json/GetStorageList.aspx"

# How long an error message may be before it is cut. The client has already
# removed the API key from anything it raises (see fulfillmen/client.py); this
# only keeps a long upstream message from filling the screen.
_MAX_ERROR = 200


def _row(raw):
    """One inventory row, in the names the screen uses.

    `TotalNumber` is what can be sold and `Number` is what is on the shelf; the
    two differ by whatever is allocated but not yet picked. Both are reported
    rather than reconciled -- the gap between them is a real fact about the
    warehouse, not a discrepancy to resolve here.
    """
    return {
        "sku": clean(raw.get("SKU")),
        "barcode": clean(raw.get("GoodsCode")),
        "available": to_number(raw.get("TotalNumber")),
        "on_hand": to_number(raw.get("Number")),
    }


@frappe.whitelist()
def list_inventory(sku=None, storage=None, page=1):
    """One page of warehouse stock.

    Permission is checked against Item: these are quantities of the site's own
    products, and anyone who may read an Item may read how many of it there are.

    Paging is the API's own -- 20 rows, fixed, not configurable -- so the page
    number passes straight through. `has_more` comes from a full page rather
    than from the response's `count`: the documentation calls that a total but
    does not guarantee it, which is why the sweep ignores it too. A catalogue
    that is an exact multiple of 20 therefore offers one empty last page, which
    is the harmless direction to be wrong in.

    Without `storage` the read spans every warehouse the account can see, and
    the response carries no warehouse field -- so a SKU held in two of them is
    two rows that cannot be told apart. They are left as they came rather than
    summed, because summing across a *paged* read would silently add up halves
    of two different pages. The caller is told which case it is in via
    `warehouse`.
    """
    from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenAPIError, FulfillmenClient
    from alaiy_os_connector_fulfillmen.fulfillmen.stock import INVENTORY_PATH, PAGE_SIZE

    frappe.has_permission("Item", "read", throw=True)

    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1

    empty = {"rows": [], "page": page, "has_more": False, "warehouse": None, "error": None}

    try:
        client = FulfillmenClient()
        # An explicit warehouse wins; otherwise the connector's configured one,
        # which is what the scheduled sweep reads, so the screen and the stored
        # Item values can never be scoped differently by accident.
        warehouse = clean(storage) or client.storage
        data = client.get(
            INVENTORY_PATH,
            page=page,
            Storage=warehouse,
            SKU=clean(sku) or None,
        )
    except FulfillmenAPIError as e:
        return {**empty, "error": str(e)[:_MAX_ERROR]}
    except Exception:
        frappe.log_error(title="Fulfillmen inventory read failed", message=frappe.get_traceback())
        return {**empty, "error": "Could not read inventory from Fulfillmen."}

    raw = data.get("data") or []
    return {
        "rows": [_row(r) for r in raw if clean(r.get("SKU"))],
        "page": page,
        "has_more": len(raw) >= PAGE_SIZE,
        "warehouse": warehouse or None,
        "error": None,
    }


@frappe.whitelist()
def list_warehouses():
    """The warehouse codes this account can see, for the picker.

    The same call `test_connection` uses to check the key, for the same reason:
    it is the cheapest read that needs nothing but the API key. An empty list
    with no error means the account genuinely has no warehouses, so the picker
    can say that rather than showing an empty dropdown.
    """
    from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenAPIError, FulfillmenClient

    frappe.has_permission("Item", "read", throw=True)

    try:
        rows = FulfillmenClient().get(STORAGE_PATH).get("data") or []
    except FulfillmenAPIError as e:
        return {"warehouses": [], "error": str(e)[:_MAX_ERROR]}
    except Exception:
        frappe.log_error(title="Fulfillmen warehouse list failed", message=frappe.get_traceback())
        return {"warehouses": [], "error": "Could not read the warehouse list from Fulfillmen."}

    codes = [clean(r.get("ShortName")) for r in rows]
    return {"warehouses": [c for c in codes if c], "error": None}
