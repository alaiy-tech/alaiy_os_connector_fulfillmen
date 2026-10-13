# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Receiving endpoint for Fulfillmen webhook notifications. Configure this URL on
the Fulfillmen side:

  https://<site>/api/method/alaiy_os_connector_fulfillmen.api.webhook.receive

It must be reachable without a login (allow_guest), so it authenticates every
request itself from the headers Fulfillmen sends (App-Key, optionally
Access-Token and X-Customer-Code) against the secrets in the settings. Anything
that does not verify is rejected before the body is read. A verified request is
acknowledged straight away with HTTP 200, as Fulfillmen requires, and processed
in the background.
"""

import frappe

from alaiy_os_connector_fulfillmen.fulfillmen.util import verify_webhook


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive():
    settings = frappe.get_single("Fulfillmen Connector Settings")
    if not settings.is_enabled:
        frappe.throw("Webhook not enabled.", frappe.PermissionError)

    ok = verify_webhook(
        frappe.request.headers,
        settings.get_password("webhook_app_key", raise_exception=False),
        settings.get_password("webhook_access_token", raise_exception=False),
        (settings.webhook_customer_code or "").strip() or None,
    )
    if not ok:
        frappe.throw("Invalid webhook credentials.", frappe.AuthenticationError)

    payload = frappe.request.get_json(silent=True)
    if not isinstance(payload, dict):
        frappe.throw("Body must be a JSON object.", frappe.ValidationError)

    frappe.enqueue(
        "alaiy_os_connector_fulfillmen.fulfillmen.sync.run_webhook",
        queue="short",
        timeout=300,
        payload=payload,
    )
    return {"success": True, "message": "Notification received successfully"}
