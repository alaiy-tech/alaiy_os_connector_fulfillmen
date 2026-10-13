# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Scheduler entry point. hooks.py runs check_and_enqueue() every minute; it reads
the interval from Fulfillmen Connector Settings and enqueues each sync only when
one is due.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

_INTERVAL_MINUTES = {"5 min": 5, "15 min": 15, "30 min": 30, "60 min": 60}

# A run "running" longer than this is treated as dead, so a crashed job never
# blocks the schedule forever.
_STALE_RUNNING_SECONDS = 1800

_JOBS = {
    "inbound": "alaiy_os_connector_fulfillmen.fulfillmen.sync.run_inbound_sync",
    "stock": "alaiy_os_connector_fulfillmen.fulfillmen.sync.run_stock_sync",
    "products": "alaiy_os_connector_fulfillmen.fulfillmen.sync.run_products_sync",
    "outbound": "alaiy_os_connector_fulfillmen.fulfillmen.sync.run_outbound_sync",
}


def check_and_enqueue():
    if not frappe.db.exists("DocType", "Fulfillmen Sync Log"):
        return

    settings = frappe.get_single("Fulfillmen Connector Settings")
    if not settings.is_enabled:
        return

    interval_minutes = _INTERVAL_MINUTES.get(settings.fulfillmen_sync_interval or "Disabled")
    if not interval_minutes:
        return

    for sync_type, method in _JOBS.items():
        _maybe_enqueue(sync_type, method, interval_minutes)


def _maybe_enqueue(sync_type, method, interval_minutes):
    now = now_datetime()

    running = frappe.db.get_value(
        "Fulfillmen Sync Log",
        {"sync_type": sync_type, "status": "running"},
        "started_at",
        order_by="started_at desc",
    )
    if running and (now - running).total_seconds() < _STALE_RUNNING_SECONDS:
        return

    last_success = frappe.db.get_value(
        "Fulfillmen Sync Log",
        {"sync_type": sync_type, "status": "success"},
        "started_at",
        order_by="started_at desc",
    )
    if last_success and now < add_to_date(last_success, minutes=interval_minutes):
        return

    frappe.enqueue(method, queue="long", timeout=900, trigger="scheduled")
