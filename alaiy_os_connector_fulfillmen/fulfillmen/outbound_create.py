# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Create, cancel and look up Fulfillmen outbound orders on demand.

This is the only write path of the connector. It is off until
"Allow creating and cancelling orders" is set in the settings, and it works from the
order data it is given: it reads no Delivery Note, Sales Order or any other
ERPNext document and creates none. The result is kept in the connector's own
"Fulfillmen Outbound Order" record, the same record the outbound sync keeps up
to date (status, waybill, tracking).

  POST /api-json/CreateOrder.aspx     create (draft or confirmed)
  POST /api-json/InterceptOrder.aspx  cancel by OrderNo or waybill
  GET  /api-json/GetShippingList.aspx service codes valid for ShippingCode
  GET  /api-json/GetStorageList.aspx  warehouse codes valid for WarehouseId

Creating twice is safe: Fulfillmen rejects a repeated customer reference
(CsRefNo, code 108). That case is treated as "already exists": the existing order
is found by its reference and stored, and nothing new is created.
"""

import frappe

from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenAPIError, FulfillmenClient
from alaiy_os_connector_fulfillmen.fulfillmen.common import retry_on_conflict, upsert
from alaiy_os_connector_fulfillmen.fulfillmen.order_payload import (
    STATUS_CONFIRMED,
    STATUS_DRAFT,
    build_create_payload,
)
from alaiy_os_connector_fulfillmen.fulfillmen.outbound import (
    DOCTYPE,
    LIST_PATH,
    fetch_order,
    refresh_order,
    store_order,
)
from alaiy_os_connector_fulfillmen.fulfillmen.util import ORDER_STATUS, clean, to_number

CREATE_PATH = "/api-json/CreateOrder.aspx"
CANCEL_PATH = "/api-json/InterceptOrder.aspx"
SHIPPING_PATH = "/api-json/GetShippingList.aspx"
STORAGE_PATH = "/api-json/GetStorageList.aspx"
DUPLICATE_REFERENCE = "108"


def _settings():
    return frappe.get_single("Fulfillmen Connector Settings")


def _require_allowed(settings):
    if not (settings.is_enabled and settings.fulfillmen_allow_order_create):
        frappe.throw("Creating and cancelling orders is off. Turn on Enable Fulfillmen and Allow creating and cancelling orders in the settings.")


def create_order(order, confirm=None):
    """
    Create one outbound order. `order` is described in order_payload.py.
    `confirm` None uses the settings ("Status When Created"), True sends it
    confirmed (status 3, Fulfillmen starts fulfilling it), False sends a draft.

    Returns {order_no, reference_no, status, status_code, tracking_no,
    duplicate}. Raises frappe.ValidationError for a problem in the order or a
    Fulfillmen refusal.
    """
    settings = _settings()
    _require_allowed(settings)

    if confirm is None:
        confirm = (settings.fulfillmen_order_status_on_create or "Draft") == "Confirmed"
    defaults = {
        "customer_id": settings.fulfillmen_customer_id,
        "shipping_code": settings.fulfillmen_default_shipping_code,
        "style": settings.fulfillmen_order_style,
        "warehouse_code": settings.fulfillmen_warehouse_code,
        "status": STATUS_CONFIRMED if confirm else STATUS_DRAFT,
    }
    try:
        payload = build_create_payload(order, defaults)
    except ValueError as e:
        frappe.throw(f"Outbound order not sent: {e}")

    client = FulfillmenClient()
    try:
        reply = client.post(CREATE_PATH, payload, idempotent=True)
        duplicate, order_no = False, clean(reply.get("OrderNo"))
        if not order_no:
            frappe.throw("Fulfillmen accepted the order but returned no order number.")
    except FulfillmenAPIError as e:
        if e.api_code != DUPLICATE_REFERENCE:
            frappe.throw(f"Fulfillmen refused the order: {e}")
        duplicate, order_no = True, _order_no_for_reference(client, payload["CsRefNo"])
        if not order_no:
            frappe.throw(f"Reference {payload['CsRefNo']} already exists at Fulfillmen but its order could not be found: {e}")
        reply = {}

    _store(client, order_no, payload, reply)
    record = frappe.db.get_value(
        DOCTYPE, order_no, ["order_no", "reference_no", "status", "status_code", "tracking_no"], as_dict=True
    ) or {}
    return {**record, "duplicate": duplicate}


def cancel_order(order_no):
    """Cancel an outbound order by order number or waybill (InterceptOrder),
    then re-read it so the stored status shows the result."""
    _require_allowed(_settings())
    order_no = clean(order_no)
    if not order_no:
        frappe.throw("order_no is required.")
    try:
        reply = FulfillmenClient().post(CANCEL_PATH, {"OrderNo": order_no}, idempotent=True)
    except FulfillmenAPIError as e:
        frappe.throw(f"Fulfillmen refused the cancel: {e}")
    refresh_order(order_no)
    frappe.db.commit()
    return {"order_no": order_no, "message": clean(reply.get("message"))}


def track_order(order_no=None, tracking_no=None):
    """
    Read one order (by system order number or waybill) from Fulfillmen, store it
    and return the stored status, waybill, tracking status and events. Works for
    any outbound order on the account, whoever created it. Read only.
    """
    order_no, tracking_no = clean(order_no), clean(tracking_no)
    if not (order_no or tracking_no):
        frappe.throw("Give order_no or tracking_no.")
    client = FulfillmenClient()
    order, lines = fetch_order(client, order_no or None, tracking_no=tracking_no or None)
    if order is None:
        frappe.throw("Fulfillmen has no outbound order for that number.")
    retry_on_conflict(store_order, client, order, lines)
    frappe.db.commit()
    return frappe.db.get_value(
        DOCTYPE,
        clean(order.get("OrderNo")),
        ["order_no", "reference_no", "status", "status_code", "shipping_code", "tracking_no",
         "tracking_status", "tracking_events", "created_at", "shipped_at"],
        as_dict=True,
    )


def shipping_services():
    """Service codes the account can ship with (valid values for ShippingCode)."""
    rows = FulfillmenClient().get(SHIPPING_PATH).get("data") or []
    return [
        {"code": clean(r.get("ShippingCode")), "name": clean(r.get("EnName")) or clean(r.get("CnName"))}
        for r in rows
    ]


def warehouses():
    """Warehouses on the account (valid values for the warehouse code)."""
    rows = FulfillmenClient().get(STORAGE_PATH).get("data") or []
    return [{"code": clean(r.get("ShortName")), "name": clean(r.get("FullName"))} for r in rows]


def _order_no_for_reference(client, reference):
    rows = client.get(LIST_PATH, CsRefNo=reference).get("data") or []
    return clean(rows[0].get("OrderNo")) if rows else ""


def _store(client, order_no, payload, reply):
    """Keep the order in the connector's own record: read it back from Fulfillmen;
    if the detail is not available yet, store what was sent and returned."""
    order, lines = fetch_order(client, order_no)
    if order is not None:
        retry_on_conflict(store_order, client, order, lines)
    else:
        code = "1" if payload["OrderStatus"] == STATUS_DRAFT else "3"
        upsert(
            DOCTYPE, order_no,
            {
                "order_no": order_no,
                "reference_no": payload["CsRefNo"],
                "status_code": code,
                "status": ORDER_STATUS.get(code, code),
                "shipping_code": payload["ShippingCode"],
                "tracking_no": clean(reply.get("TrackingNo")),
            },
            [{"sku": p["SKU"], "quantity": to_number(p["Quantity"])} for p in payload["Products"]],
        )
    frappe.db.commit()
