# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Whitelisted entry points for outbound orders. They work from the data passed in
and touch no ERPNext document; results are kept in "Fulfillmen Outbound Order".
Creating and cancelling are off until "Allow creating and cancelling orders" is set.
"""

import frappe

_ROLES = ("System Manager",)


@frappe.whitelist()
def create_outbound_order(order, confirm=None):
    """Create an outbound order. `order` is a JSON object (see
    fulfillmen/order_payload.py for the keys). `confirm`: 1 sends it confirmed,
    0 as a draft, empty uses the settings."""
    frappe.only_for(_ROLES)
    from alaiy_os_connector_fulfillmen.fulfillmen.outbound_create import create_order

    if isinstance(order, str):
        order = frappe.parse_json(order)
    if confirm in (None, ""):
        confirm = None
    else:
        confirm = str(confirm).lower() in ("1", "true", "yes")
    return create_order(order, confirm=confirm)


@frappe.whitelist()
def cancel_outbound_order(order_no):
    """Cancel an outbound order by order number or waybill."""
    frappe.only_for(_ROLES)
    from alaiy_os_connector_fulfillmen.fulfillmen.outbound_create import cancel_order

    return cancel_order(order_no)


@frappe.whitelist()
def track_outbound_order(order_no=None, tracking_no=None):
    """Read one outbound order and its tracking from Fulfillmen and store it.
    Read only; works for any outbound order on the account."""
    frappe.only_for(_ROLES)
    from alaiy_os_connector_fulfillmen.fulfillmen.outbound_create import track_order

    return track_order(order_no, tracking_no)


@frappe.whitelist()
def list_shipping_services():
    """Valid ShippingCode values for the account."""
    frappe.only_for(_ROLES)
    from alaiy_os_connector_fulfillmen.fulfillmen.outbound_create import shipping_services

    return shipping_services()


@frappe.whitelist()
def list_warehouses():
    """Valid warehouse codes for the account."""
    frappe.only_for(_ROLES)
    from alaiy_os_connector_fulfillmen.fulfillmen.outbound_create import warehouses

    return warehouses()
