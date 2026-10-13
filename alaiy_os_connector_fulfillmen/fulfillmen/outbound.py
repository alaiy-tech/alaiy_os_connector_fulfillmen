# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Outbound orders. Reads Fulfillmen outbound orders (goods leaving the warehouse,
for example for the first-mile carrier) and their tracking, and keeps one
"Fulfillmen Outbound Order" record per order, named by the order number. The
connector creates no Delivery Note or any other document, and nothing is created
or changed in Fulfillmen: documents are made later, outside the connector, from
these records.

  GET /api-json/GetOrderList.aspx     list by OrderStatus / StartTime / EndTime (20 per page)
  GET /api-json/GetOrderDetails.aspx  one order by OrderNo: status code, TrackingNo, DeliveryTime, lines
  GET /api-json/GetTrackingInfo.aspx  tracking events by waybill (No=)

Stored: CsRefNo (reference_no), status code and label, shipping service, waybill,
created and ship time (DeliveryTime), tracking status and events, and the SKU and
quantity of each line.

Which orders are read: every order in a live status (3 confirmed, 4 and 5 pending
delivery, 11 processing, 12 out of stock), shipped orders (6) created within the
look-back window in the settings, and any stored record in a live status that the
sweep did not return, so a move to shipped or deleted is not missed. Tracking is
fetched for shipped orders that have a waybill and stops once it reads Signed. The
docs do not say when Fulfillmen deducts its own stock for an order, so no stock is
derived from order status. The `delivery_note` link is never written here.
"""

import frappe
from frappe.utils import add_days, getdate

from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenClient
from alaiy_os_connector_fulfillmen.fulfillmen.common import fail, new_result, retry_on_conflict, tally, upsert
from alaiy_os_connector_fulfillmen.fulfillmen.util import (
    ORDER_STATUS,
    POLLED_ORDER_STATUSES,
    SHIPPED_ORDER_STATUS,
    TRACKING_DONE,
    TRACKING_STATUS,
    clean,
    events_text,
    to_datetime,
    to_number,
)

LIST_PATH = "/api-json/GetOrderList.aspx"
DETAIL_PATH = "/api-json/GetOrderDetails.aspx"
TRACK_PATH = "/api-json/GetTrackingInfo.aspx"
LIST_PAGE_SIZE = 20   # fixed by the API
DOCTYPE = "Fulfillmen Outbound Order"


def _order_numbers(client, **filters):
    return [clean(r.get("OrderNo")) for r in client.pages(LIST_PATH, "page", LIST_PAGE_SIZE, **filters) if r.get("OrderNo")]


def fetch_order(client, order_no):
    """(header dict, line dicts) for an order, or (None, [])."""
    data = client.get(DETAIL_PATH, OrderNo=order_no)
    rows = (data.get("Order") or {}).get("data") or []
    return (rows[0], (data.get("Details") or {}).get("data") or []) if rows else (None, [])


def fetch_tracking(client, waybill):
    """(status code, events) for a waybill, or (None, []) when there is none."""
    data = client.get(TRACK_PATH, No=waybill)
    code = data.get("Status")
    return (None if code in (None, "") else str(code)), data.get("data") or []


def store_order(client, order, lines):
    """Create or update the record for one order. Returns 'updated' or
    'unchanged'. Raises on a save error."""
    order_no = clean(order.get("OrderNo"))
    if not order_no:
        return "unchanged"   # an order without a number cannot be keyed

    code = clean(order.get("OrderStatus"))
    waybill = clean(order.get("TrackingNo"))
    values = {
        "order_no": order_no,
        "reference_no": clean(order.get("CsRefNo")),
        "status_code": code,
        "status": ORDER_STATUS.get(code, code),
        "shipping_code": clean(order.get("ShippingCode")),
        "tracking_no": waybill,
        "created_at": to_datetime(order.get("CreateTime")),
        "shipped_at": to_datetime(order.get("DeliveryTime")),
    }

    if code == SHIPPED_ORDER_STATUS and waybill:
        stored = frappe.db.get_value(DOCTYPE, order_no, "tracking_status_code") if frappe.db.exists(DOCTYPE, order_no) else ""
        if clean(stored) not in TRACKING_DONE:
            t_code, events = fetch_tracking(client, waybill)
            values["tracking_status_code"] = t_code or ""
            values["tracking_status"] = TRACKING_STATUS.get(t_code, "") if t_code else ""
            values["tracking_events"] = events_text(events)

    rows = [
        {"sku": clean(line.get("SKU")), "quantity": to_number(line.get("Quantity"))}
        for line in lines if clean(line.get("SKU"))
    ]
    return upsert(DOCTYPE, order_no, values, rows)


def store_numbers(client, order_nos, result, seen=None):
    for order_no in order_nos:
        if seen is not None:
            seen.add(order_no)
        try:
            order, lines = fetch_order(client, order_no)
            if order is None:
                result["processed"] += 1
                continue
            tally(result, retry_on_conflict(store_order, client, order, lines))
        except Exception:
            fail(result, f"Fulfillmen outbound update failed: {order_no}")


def _lookback_start():
    days = frappe.db.get_single_value("Fulfillmen Connector Settings", "fulfillmen_outbound_lookback_days") or 30
    return f"{add_days(getdate(), -int(days))} 00:00:00"


def sync_outbound():
    client = FulfillmenClient()
    result, seen = new_result(), set()

    for status in POLLED_ORDER_STATUSES:
        store_numbers(client, _order_numbers(client, OrderStatus=status), result, seen)
    store_numbers(
        client,
        _order_numbers(client, OrderStatus=SHIPPED_ORDER_STATUS, StartTime=_lookback_start()),
        result, seen,
    )

    # Stored in a live status but absent from the sweep: it has moved on. Read it
    # directly so the new state is stored.
    live = frappe.get_all(DOCTYPE, filters={"status_code": ["in", POLLED_ORDER_STATUSES]}, pluck="name")
    store_numbers(client, sorted(set(live) - seen), result)
    return result


def refresh_order(order_no):
    """Targeted re-pull for one order (webhook)."""
    result = new_result()
    store_numbers(FulfillmenClient(), [order_no], result)
    return result
