# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Whitelisted entry points for a screen showing warehouse stock.

Thin, like api/sync.py: check permission, call fulfillmen/stock.py, shape the
failure. Nothing here knows the API's paths, its field names or its page size
-- stock.py owns the inventory endpoint, and the sweep and these reads go
through the same code so the two cannot answer differently.

Read only, and the call only ever happens server-side: the API key is a URL
query parameter at Fulfillmen, so a browser making this call itself would put
the key in a URL the person can read.

Failures are returned, never raised. An empty table and an unreachable
warehouse are different answers, and a screen that cannot tell them apart
reports "no stock" for an outage.
"""

import frappe

# Enough of an upstream message to be useful, not enough to fill a screen. The
# client has already removed the API key from anything it raises.
_MAX_ERROR = 200


def _page_number(value):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


@frappe.whitelist()
def list_inventory(sku=None, storage=None, page=1):
    """One page of warehouse stock, live.

    Permission is checked against Item: these are quantities of the site's own
    products, and anyone who may read an Item may read how many there are.
    """
    from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenAPIError
    from alaiy_os_connector_fulfillmen.fulfillmen.stock import read_page

    frappe.has_permission("Item", "read", throw=True)
    page = _page_number(page)
    empty = {"rows": [], "page": page, "has_more": False, "warehouse": None, "error": None}

    try:
        return {**empty, **read_page(sku=sku, storage=storage, page=page)}
    except FulfillmenAPIError as e:
        return {**empty, "error": str(e)[:_MAX_ERROR]}
    except Exception:
        frappe.log_error(title="Fulfillmen inventory read failed", message=frappe.get_traceback())
        return {**empty, "error": "Could not read inventory from Fulfillmen."}


@frappe.whitelist()
def list_warehouses():
    """The warehouse codes this account can see, for a picker.

    An empty list with no error means the account genuinely has no warehouses,
    so a picker can say that rather than showing an empty dropdown.
    """
    from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenAPIError
    from alaiy_os_connector_fulfillmen.fulfillmen.stock import warehouse_codes

    frappe.has_permission("Item", "read", throw=True)

    try:
        return {"warehouses": warehouse_codes(), "error": None}
    except FulfillmenAPIError as e:
        return {"warehouses": [], "error": str(e)[:_MAX_ERROR]}
    except Exception:
        frappe.log_error(title="Fulfillmen warehouse list failed", message=frappe.get_traceback())
        return {"warehouses": [], "error": "Could not read the warehouse list from Fulfillmen."}
