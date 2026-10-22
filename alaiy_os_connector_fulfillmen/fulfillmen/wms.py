# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Exact clone of the Fulfillmen API for products (read), inbound, stock, warehouses
and outbound orders.

Each function of `api/wms.py` maps to one Fulfillmen endpoint (same path, same
query and body fields, same reply). The request is passed through as given and
Fulfillmen's reply comes back unchanged, success or failure, so a client written
against the Fulfillmen docs works against this API as it is. The connector adds
the API key itself and refuses any `Key` it is handed.

Beyond the pass-through, only two things are added:
  - the calls that change something at Fulfillmen (create or cancel an inbound or
    outbound order, upload label) are refused until "Allow creating and cancelling
    orders" is set in the settings;
  - after a create or a cancel the order is saved or re-read in the connector's own
    "Fulfillmen Outbound Order" or "Fulfillmen Inbound Order" record, so the sync and
    webhook keep its status current. A failure there never changes the reply.

No ERPNext document is read or written.

Endpoints (Fulfillmen docs section in brackets):
  get_goods_list     GET  GetGoodsList.aspx      [3]   product list
  create_asn         POST CreateASN.aspx         [4]   create inbound order
  get_grn_list       GET  getGRNlist.aspx        [5]   inbound order query
  cancel_asn         POST CancelASN.aspx         [6]   cancel inbound order
  create_order       POST CreateOrder.aspx       [7]
  get_order_list     GET  GetOrderList.aspx      [8]
  get_order_details  GET  GetOrderDetails.aspx   [9]
  intercept_order    POST InterceptOrder.aspx    [10]  order cancel
  upload_label       POST UploadLabel.aspx       [11]
  get_label_pdf      POST GetLabelPDF.aspx       [12]
  get_tracking_info  GET  GetTrackingInfo.aspx   [13]
  get_price          POST GetPrice.aspx          [14]  freight quote
  get_inventory_list GET  getinventorylist.aspx  [15]
  get_country_list   GET  GetCountryList.aspx    [29]
  get_shipping_list  GET  GetShippingList.aspx   [30]
  get_storage_list   GET  GetStorageList.aspx    [31]
"""

import frappe

from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenClient

# name: (method, path, changes something at Fulfillmen)
ENDPOINTS = {
    "get_goods_list": ("GET", "/api-json/GetGoodsList.aspx", False),
    "create_asn": ("POST", "/api-json/CreateASN.aspx", True),
    "get_grn_list": ("GET", "/api-json/getGRNlist.aspx", False),
    "cancel_asn": ("POST", "/api-json/CancelASN.aspx", True),
    "create_order": ("POST", "/api-json/CreateOrder.aspx", True),
    "get_order_list": ("GET", "/api-json/GetOrderList.aspx", False),
    "get_order_details": ("GET", "/api-json/GetOrderDetails.aspx", False),
    "intercept_order": ("POST", "/api-json/InterceptOrder.aspx", True),
    "upload_label": ("POST", "/api-json/UploadLabel.aspx", True),
    "get_label_pdf": ("POST", "/api-json/GetLabelPDF.aspx", False),
    "get_tracking_info": ("GET", "/api-json/GetTrackingInfo.aspx", False),
    "get_price": ("POST", "/api-json/GetPrice.aspx", False),
    "get_inventory_list": ("GET", "/api-json/getinventorylist.aspx", False),
    "get_country_list": ("GET", "/api-json/GetCountryList.aspx", False),
    "get_shipping_list": ("GET", "/api-json/GetShippingList.aspx", False),
    "get_storage_list": ("GET", "/api-json/GetStorageList.aspx", False),
}


def _is_success(reply):
    code = str(reply.get("Code") or reply.get("code") or "")
    return code == "100" or str(reply.get("success")).lower() == "true"


def call(name, params=None, body=None):
    """Run one cloned endpoint and return Fulfillmen's reply unchanged."""
    method, path, writes = ENDPOINTS[name]
    if writes:
        from alaiy_os_connector_fulfillmen.fulfillmen.outbound_create import _require_allowed

        _require_allowed(frappe.get_single("Fulfillmen Connector Settings"))

    params = {k: v for k, v in (params or {}).items() if str(k).lower() != "key"}
    if isinstance(body, dict):
        body = {k: v for k, v in body.items() if str(k).lower() != "key"}

    # Retry a POST only where repeating it is harmless: an outbound create carries a
    # customer reference that Fulfillmen rejects when used twice; a cancel, a label
    # upload, a label print and a quote give the same result when repeated. An inbound
    # create has no such rule in the docs, so it is sent once.
    idempotent = {"create_order": bool((body or {}).get("CsRefNo")), "create_asn": False}.get(name, method == "POST")

    client = FulfillmenClient()
    reply = client.send(method, path, params, body, idempotent=idempotent)
    if _is_success(reply):
        _keep_record(name, client, body, reply)
    return reply


def _keep_record(name, client, body, reply):
    """Save a created order, or re-read a cancelled outbound order or a created or
    cancelled inbound order, in the connector's own records. Best effort: the reply
    to the caller is never affected."""
    if name not in ("create_order", "intercept_order", "create_asn", "cancel_asn"):
        return
    try:
        from alaiy_os_connector_fulfillmen.fulfillmen.outbound import refresh_order
        from alaiy_os_connector_fulfillmen.fulfillmen.outbound_create import _store
        from alaiy_os_connector_fulfillmen.fulfillmen.util import clean

        if name == "create_order" and clean(reply.get("OrderNo")):
            _store(client, clean(reply["OrderNo"]), _as_payload(body), reply)
        elif name == "intercept_order" and clean((body or {}).get("OrderNo")):
            refresh_order(clean(body["OrderNo"]))
            frappe.db.commit()
        elif name == "create_asn" and clean(reply.get("ASNNumber")):
            _refresh_asn(clean(reply["ASNNumber"]))
        elif name == "cancel_asn" and clean((body or {}).get("ASNNumber")):
            _refresh_asn(clean(body["ASNNumber"]))
    except Exception:
        frappe.log_error(title="Fulfillmen: saving the order record failed", message=frappe.get_traceback())


def _as_payload(body):
    """The pieces _store reads, taken from a CreateOrder body."""
    return {
        "OrderStatus": int(str(body.get("OrderStatus") or 1)),
        "CsRefNo": str(body.get("CsRefNo") or ""),
        "ShippingCode": str(body.get("ShippingCode") or ""),
        "Products": [
            {"SKU": str(p.get("SKU") or ""), "Quantity": p.get("Quantity") or 0}
            for p in (body.get("Products") or []) if isinstance(p, dict)
        ],
    }


def _refresh_asn(asn_number):
    from alaiy_os_connector_fulfillmen.fulfillmen.inbound import refresh_asn

    refresh_asn(asn_number)
    frappe.db.commit()
