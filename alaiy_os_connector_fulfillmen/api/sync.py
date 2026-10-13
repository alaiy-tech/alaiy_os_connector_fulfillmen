# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Whitelisted entry points the Alaiy OS connector card and the settings form call.
Thin: create the log so it shows as "queued" immediately, then enqueue the work
on the long queue.
"""

import frappe

from alaiy_os_connector_fulfillmen.fulfillmen.sync import get_or_create_log

_METHODS = {
    "inbound": "alaiy_os_connector_fulfillmen.fulfillmen.sync.run_inbound_sync",
    "stock": "alaiy_os_connector_fulfillmen.fulfillmen.sync.run_stock_sync",
    "products": "alaiy_os_connector_fulfillmen.fulfillmen.sync.run_products_sync",
    "outbound": "alaiy_os_connector_fulfillmen.fulfillmen.sync.run_outbound_sync",
}


def _trigger(sync_type):
    log = get_or_create_log(sync_type, "manual")
    frappe.enqueue(_METHODS[sync_type], queue="long", timeout=900, trigger="manual", log_name=log.name)
    return {"queued": True, "log_name": log.name}


@frappe.whitelist()
def trigger_inbound_sync():
    """Manually pull incoming shipments onto Purchase Orders."""
    return _trigger("inbound")


@frappe.whitelist()
def trigger_stock_sync():
    """Manually pull warehouse stock onto Items."""
    return _trigger("stock")


@frappe.whitelist()
def trigger_products_sync():
    """Manually pull registered products (QC measurements) onto Items."""
    return _trigger("products")


@frappe.whitelist()
def trigger_outbound_sync():
    """Manually pull outbound orders and tracking onto Delivery Notes."""
    return _trigger("outbound")


@frappe.whitelist()
def get_sync_status(sync_type=None):
    """Most recent Fulfillmen Sync Log rows, newest first. The connector card
    passes its slot name ("categories" = inbound, "items" = stock)."""
    filters = {}
    if sync_type:
        filters["sync_type"] = {"categories": "inbound", "items": "stock"}.get(sync_type, sync_type)
    return frappe.get_all(
        "Fulfillmen Sync Log",
        filters=filters,
        fields=[
            "name", "sync_type", "trigger", "status",
            "started_at", "finished_at",
            "items_processed", "items_updated", "items_unmatched", "items_failed",
            "error_message",
        ],
        order_by="started_at desc",
        limit=5,
    )
