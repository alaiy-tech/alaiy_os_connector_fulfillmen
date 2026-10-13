# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Fulfillmen Sync Log lifecycle plus the runs the connector has:

  inbound   incoming shipments (ASN)        -> Fulfillmen Inbound Order records
  stock     warehouse inventory             -> Item fields
  products  products registered at the WMS  -> Item fields
  outbound  outbound orders and tracking    -> Fulfillmen Outbound Order records
  webhook   one notification                -> a targeted re-pull of that ASN / SKU / order

Every run records queued / running / success / failed with counts. `failed` is
set only when something errored; rows that simply have no matching ERPNext
record are counted as `unmatched` and do not fail the run.
"""

import frappe
from frappe.utils import now_datetime


def get_or_create_log(sync_type, trigger, log_name=None):
    """Return the Sync Log for this run. A pre-created log_name (made by the API
    layer so it shows as 'queued' immediately) is reused."""
    if log_name and frappe.db.exists("Fulfillmen Sync Log", log_name):
        return frappe.get_doc("Fulfillmen Sync Log", log_name)

    log = frappe.new_doc("Fulfillmen Sync Log")
    log.sync_type = sync_type
    log.trigger = trigger
    log.status = "queued"
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return log


def _mark_running(log):
    log.status = "running"
    log.started_at = now_datetime()
    log.save(ignore_permissions=True)
    frappe.db.commit()


def _mark_finished(log, status, error_message=None):
    log.status = status
    log.finished_at = now_datetime()
    if error_message:
        log.error_message = error_message[:2000]
    log.save(ignore_permissions=True)
    frappe.db.commit()


def _run(sync_type, trigger, log_name, worker):
    """worker(log) -> dict with processed/updated/unmatched/failed (and optional
    notes). Unexpected exceptions mark the log failed and are re-raised."""
    log = get_or_create_log(sync_type, trigger, log_name)
    _mark_running(log)
    try:
        result = worker()
    except Exception:
        _mark_finished(log, "failed", frappe.get_traceback())
        frappe.log_error(title=f"Fulfillmen {sync_type} sync failed", message=frappe.get_traceback())
        raise

    log.items_processed = result["processed"]
    log.items_updated = result["updated"]
    log.items_unmatched = result["unmatched"]
    log.items_failed = result["failed"]
    notes = result.get("notes") or []
    if result["failed"]:
        notes.insert(0, f"{result['failed']} record(s) failed -- see Error Log.")
    _mark_finished(log, "failed" if result["failed"] else "success", "\n".join(notes) or None)
    return result


def run_inbound_sync(trigger="scheduled", log_name=None):
    from alaiy_os_connector_fulfillmen.fulfillmen.inbound import sync_inbound
    return _run("inbound", trigger, log_name, sync_inbound)


def run_stock_sync(trigger="scheduled", log_name=None):
    from alaiy_os_connector_fulfillmen.fulfillmen.stock import sync_stock
    return _run("stock", trigger, log_name, sync_stock)


def run_products_sync(trigger="scheduled", log_name=None):
    from alaiy_os_connector_fulfillmen.fulfillmen.products import sync_products
    return _run("products", trigger, log_name, sync_products)


def run_outbound_sync(trigger="scheduled", log_name=None):
    from alaiy_os_connector_fulfillmen.fulfillmen.outbound import sync_outbound
    return _run("outbound", trigger, log_name, sync_outbound)


def run_webhook(payload, log_name=None):
    from alaiy_os_connector_fulfillmen.fulfillmen.webhooks import handle_notification
    return _run("webhook", "webhook", log_name, lambda: handle_notification(payload))
