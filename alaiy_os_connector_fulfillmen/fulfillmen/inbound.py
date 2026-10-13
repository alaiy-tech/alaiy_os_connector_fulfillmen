# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Incoming shipments. Reads Fulfillmen inbound orders (ASN) and keeps one
"Fulfillmen Inbound Order" record per ASN, named by the ASN number, with its
status and per-SKU quantities. The connector creates no Purchase Order or any
other document, and nothing is created or changed in Fulfillmen: documents are
made later, outside the connector, from these records.

  GET /api-json/getGRNlist.aspx   (filters: ASNStatus, ASNNumber, page, pageSize<=100)

Stored per ASN: ReferenceNo, status (English label from the code; the API text is
Chinese) and code, warehouse name, created and completion time, number of boxes
flagged damaged. Stored per detail line, as Fulfillmen reports them:

  ShouldQuantity  expected (announced)      -> expected_qty
  OKQuantity      received, passed QC       -> ok_qty
  FactQuantity    received, failed QC       -> failed_qty
  Quantity        put on the shelf          -> shelved_qty

A record is written only when something changed. Terminal ASNs (deleted, void,
completed) are not polled; a stored record in a live status that the sweep did not
return is re-read by its ASN number, so the move to a terminal state is stored.
Photo links (box and QC images) are signed and expire in about two hours, so they
are not stored. The `purchase_order` link on the record is never written here.
"""

from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenClient
from alaiy_os_connector_fulfillmen.fulfillmen.common import fail, new_result, retry_on_conflict, tally, upsert
from alaiy_os_connector_fulfillmen.fulfillmen.util import (
    ASN_STATUS,
    POLLED_ASN_STATUSES,
    TERMINAL_ASN_STATUSES,
    clean,
    to_datetime,
    to_number,
)

import frappe

ASN_PATH = "/api-json/getGRNlist.aspx"
PAGE_SIZE = 100   # documented maximum
DOCTYPE = "Fulfillmen Inbound Order"


def _fetch(client, **filters):
    return client.pages(ASN_PATH, "page", PAGE_SIZE, pageSize=PAGE_SIZE, **filters)


def fetch_asn(client, asn_number):
    """The ASN row with exactly this number, or None. ASNNumber is a contains
    match in the API, so the exact row is picked out."""
    for row in _fetch(client, ASNNumber=asn_number):
        if row.get("ASNNumber") == asn_number:
            return row
    return None


def store_asn(row):
    """Create or update the record for one ASN row. Returns 'updated' or
    'unchanged'. Raises on a save error (the caller counts it as failed)."""
    asn = clean(row.get("ASNNumber"))
    if not asn:
        return "unchanged"   # a row without a number cannot be keyed
    code = clean(row.get("ASNStatus"))
    values = {
        "asn_number": asn,
        "reference_no": clean(row.get("ReferenceNo")),
        "status_code": code,
        "status": ASN_STATUS.get(code) or clean(row.get("ASNStatusText")),
        "warehouse": clean(row.get("FullName")),
        "created_at": to_datetime(row.get("CreateTime")),
        "completed_at": to_datetime(row.get("CompletionTime")),
        "damaged_boxes": sum(1 for box in row.get("BoxImages") or [] if box.get("IsDamaged")),
    }
    rows = [
        {
            "sku": clean(d.get("SKU")),
            "goods_code": clean(d.get("GoodsCode")),
            "expected_qty": to_number(d.get("ShouldQuantity")),
            "ok_qty": to_number(d.get("OKQuantity")),
            "failed_qty": to_number(d.get("FactQuantity")),
            "shelved_qty": to_number(d.get("Quantity")),
        }
        for d in row.get("details") or []
        if clean(d.get("SKU"))
    ]
    return upsert(DOCTYPE, asn, values, rows)


def store_rows(rows, result, seen=None):
    for row in rows:
        asn = row.get("ASNNumber")
        if seen is not None:
            seen.add(asn)
        try:
            tally(result, retry_on_conflict(store_asn, row))
        except Exception:
            fail(result, f"Fulfillmen inbound update failed: {asn}")


def sync_inbound():
    client = FulfillmenClient()
    result, seen = new_result(), set()

    for status in POLLED_ASN_STATUSES:
        store_rows(_fetch(client, ASNStatus=status), result, seen)

    # Stored in a live status but absent from the sweep: it has moved on (usually
    # to completed). Read it directly so the final state is stored.
    live = frappe.get_all(DOCTYPE, filters={"status_code": ["not in", list(TERMINAL_ASN_STATUSES)]}, pluck="name")
    for asn in set(live) - seen:
        row = fetch_asn(client, asn)
        if row:
            store_rows([row], result)
    return result


def refresh_asn(asn_number):
    """Targeted re-pull for one ASN (webhook)."""
    result = new_result()
    row = fetch_asn(FulfillmenClient(), asn_number)
    if row:
        store_rows([row], result)
    else:
        result["notes"].append(f"Inbound order {asn_number} not found.")
    return result
