# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Install / migrate plumbing shared by every Alaiy OS connector:

  sync_connector_registry  -> (re)register in OS Connector Registry (every migrate)
  setup_custom_fields      -> read-only stock / product fields on Item; runs on first
                              enable from the settings form, and again after every
                              migrate while the connector is enabled, so fields
                              added by an upgrade appear without a re-enable

Shipment data lives in the connector's own staging doctypes (Fulfillmen Inbound
Order, Fulfillmen Outbound Order) and needs no custom field. This connector
creates no Purchase Order, Delivery Note, Sales Invoice or any other document.
"""

import frappe

MODULE = "Alaiy Os Connector Fulfillmen"


def after_install():
    pass


def sync_connector_registry():
    """Register or update this connector's row in alaiy_os's OS Connector
    Registry. Idempotent; runs on every bench migrate."""
    _fix_settings_as_single()

    if not frappe.db.exists("DocType", "OS Connector Registry"):
        return

    from alaiy_os_connector_fulfillmen.connector_meta import connector_meta

    connector_id = connector_meta["connector_id"]
    if frappe.db.exists("OS Connector Registry", connector_id):
        doc = frappe.get_doc("OS Connector Registry", connector_id)
    else:
        doc = frappe.new_doc("OS Connector Registry")

    # Owned by the running system, never overwritten from static meta.
    runtime_fields = {"connection_status", "last_tested_at"}

    for key, val in connector_meta.items():
        if not hasattr(doc, key):
            continue
        if doc.is_new() or key not in runtime_fields:
            doc.set(key, val)
    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    frappe.db.commit()
    _update_alaiy_os_sidebar()
    if frappe.db.get_single_value("Fulfillmen Connector Settings", "is_enabled"):
        setup_custom_fields()


def _update_alaiy_os_sidebar():
    """Re-run alaiy_os's sidebar provisioning so the Logs link and connector card
    show up right after registration."""
    try:
        from alaiy_os.setup.install import (
            create_or_update_os_settings_workspace,
            create_or_update_os_settings_workspace_sidebar,
            create_or_update_workspace_sidebar,
        )
        create_or_update_workspace_sidebar()
        create_or_update_os_settings_workspace()
        create_or_update_os_settings_workspace_sidebar()
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            title="Fulfillmen connector: sidebar update failed",
            message=frappe.get_traceback(),
        )


def _fix_settings_as_single():
    """Frappe does not convert an existing DocType from table-based to Single on
    migrate, so force issingle=1 on every deploy."""
    frappe.db.sql(
        "UPDATE `tabDocType` SET issingle=1 "
        "WHERE name='Fulfillmen Connector Settings' AND issingle=0"
    )
    frappe.db.commit()


def setup_custom_fields():
    """Add the Item fields the stock and product syncs write. All read-only.
    Idempotent."""
    item_fields = [
        {"fieldname": "fulfillmen_registered", "label": "Registered At Fulfillmen", "fieldtype": "Check",
         "insert_after": "item_name"},
        {"fieldname": "fulfillmen_barcode", "label": "Fulfillmen Barcode", "fieldtype": "Data",
         "insert_after": "fulfillmen_registered"},
        {"fieldname": "fulfillmen_available_stock", "label": "Fulfillmen Available Stock", "fieldtype": "Float",
         "insert_after": "fulfillmen_barcode"},
        {"fieldname": "fulfillmen_shelf_stock", "label": "Fulfillmen Shelf Stock", "fieldtype": "Float",
         "insert_after": "fulfillmen_available_stock"},
        {"fieldname": "fulfillmen_stock_synced_at", "label": "Fulfillmen Stock Synced At", "fieldtype": "Datetime",
         "insert_after": "fulfillmen_shelf_stock"},
        {"fieldname": "fulfillmen_qc_weight", "label": "Fulfillmen QC Weight", "fieldtype": "Float",
         "insert_after": "fulfillmen_stock_synced_at", "description": "Measured by the warehouse at QC; empty until inspected."},
        {"fieldname": "fulfillmen_qc_length", "label": "Fulfillmen QC Length", "fieldtype": "Float",
         "insert_after": "fulfillmen_qc_weight"},
        {"fieldname": "fulfillmen_qc_width", "label": "Fulfillmen QC Width", "fieldtype": "Float",
         "insert_after": "fulfillmen_qc_length"},
        {"fieldname": "fulfillmen_qc_height", "label": "Fulfillmen QC Height", "fieldtype": "Float",
         "insert_after": "fulfillmen_qc_width"},
    ]

    _ensure_custom_fields("Item", item_fields)
    frappe.db.commit()


def _ensure_custom_fields(doctype, fields):
    for f in fields:
        key = f"{doctype}-{f['fieldname']}"
        if frappe.db.exists("Custom Field", key):
            if f.get("description"):
                frappe.db.set_value("Custom Field", key, "description", f["description"])
            continue
        cf = frappe.new_doc("Custom Field")
        cf.dt = doctype
        cf.fieldname = f["fieldname"]
        cf.label = f["label"]
        cf.fieldtype = f["fieldtype"]
        cf.insert_after = f.get("insert_after", "")
        cf.search_index = 1 if f.get("search_index") else 0
        cf.hidden = 1 if f.get("hidden") else 0
        cf.read_only = 1
        cf.description = f.get("description", "")
        cf.module = MODULE
        cf.insert(ignore_permissions=True)
