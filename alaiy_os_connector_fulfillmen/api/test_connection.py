# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Reachability and key check. Wired into the registry via
connector_meta["test_method"] and called by the "Test Connection" button.
Always returns {"success": bool, "message": str} -- never raises to the caller.

There is no ping route. The warehouse list is the cheapest read that needs only
the API key (the account-info call wants a username and password, which this
connector never stores), so it doubles as the key check.
"""

import frappe


@frappe.whitelist()
def test_connection():
    from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenAPIError, FulfillmenClient

    try:
        client = FulfillmenClient()
        rows = client.get("/api-json/GetStorageList.aspx").get("data") or []
        codes = [str(r.get("ShortName") or "").strip() for r in rows]
        if client.storage and client.storage not in codes:
            return {"success": False, "message": f"Key accepted, but warehouse code {client.storage!r} is not in the account's list ({', '.join(codes) or 'empty'})."}
        return {"success": True, "message": f"Connected. {len(rows)} warehouse(s) visible: {', '.join(codes[:5])}."}
    except FulfillmenAPIError as e:
        return {"success": False, "message": str(e)[:200]}
    except Exception as e:
        return {"success": False, "message": str(e)[:200]}
