# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Helpers shared by the sync modules."""

import frappe
from frappe.utils import now_datetime

# A sweep and a webhook can save the same document at the same moment; the
# loser gets a timestamp conflict. getattr keeps this importable where the
# exception does not exist.
_CONFLICT = getattr(frappe, "TimestampMismatchError", ())


def new_result():
    return {"processed": 0, "updated": 0, "unmatched": 0, "failed": 0, "notes": []}


def retry_on_conflict(fn, *args, **kwargs):
    """Call fn; if the document changed underneath it, run it once more (it
    re-reads the document)."""
    try:
        return fn(*args, **kwargs)
    except _CONFLICT:
        return fn(*args, **kwargs)


def tally(result, outcome):
    result["processed"] += 1
    if outcome == "updated":
        result["updated"] += 1
    elif outcome == "unmatched":
        result["unmatched"] += 1


def fail(result, title):
    result["processed"] += 1
    result["failed"] += 1
    frappe.log_error(title=title, message=frappe.get_traceback())


def _norm(value):
    """None, "" and 0 compare equal; numbers stay numbers, text stays text."""
    return (value or 0) if isinstance(value, (int, float)) else (value or "")


def put(doc, field, value, changed):
    """Set doc[field] = value only when it differs; returns the updated
    `changed` flag."""
    if _norm(doc.get(field)) == _norm(value):
        return changed
    doc.set(field, value)
    return True


def upsert(doctype, key, values, rows=None):
    """Create or update the Fulfillmen staging record named `key`.

    `values` are the parent fields (including the key field itself); `rows` is
    the full list of child-table dicts for `items`, or None to leave the table
    alone. The record is written only when something changed. Returns 'updated'
    (created or changed) or 'unchanged'. Never touches the link field a later
    process fills in (purchase_order / delivery_note)."""
    if frappe.db.exists(doctype, key):
        doc, changed = frappe.get_doc(doctype, key), False
    else:
        doc, changed = frappe.new_doc(doctype), True

    for field, value in values.items():
        changed = put(doc, field, value, changed)

    if rows is not None:
        keys = rows[0].keys() if rows else []
        current = [{k: _norm(r.get(k)) for k in keys} for r in doc.get("items") or []]
        if current != [{k: _norm(v) for k, v in r.items()} for r in rows]:
            doc.set("items", rows)
            changed = True

    if not changed:
        return "unchanged"
    doc.last_updated_at = now_datetime()
    if doc.get("__islocal") or not frappe.db.exists(doctype, key):
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    return "updated"
