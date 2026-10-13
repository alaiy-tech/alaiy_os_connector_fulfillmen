# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Webhook handling. Fulfillmen POSTs a JSON notification to a URL they configure
for us; the notification only tells us WHAT changed. We never trust its payload
as data: each type triggers a targeted re-pull through the authenticated API,
and the stored values come from that response.

  type 3  inbound order status   -> re-read that ASN        (data.inboundNo)
  type 2  product / stock change -> re-read that SKU        (data.productSku)
  type 1  outbound order status  -> re-read that order      (data.orderNo)

The receiving endpoint is api/webhook.py.
"""

from alaiy_os_connector_fulfillmen.fulfillmen import inbound, outbound, stock


def handle_notification(payload):
    kind = payload.get("type")
    data = payload.get("data") or {}

    if kind == 3 and data.get("inboundNo"):
        return inbound.refresh_asn(str(data["inboundNo"]))
    if kind == 2 and data.get("productSku"):
        return stock.refresh_sku(str(data["productSku"]))

    if kind == 1 and data.get("orderNo"):
        return outbound.refresh_order(str(data["orderNo"]))

    return {"processed": 0, "updated": 0, "unmatched": 0, "failed": 0,
            "notes": [f"Ignored notification type {kind!r} (missing reference or unknown type)."]}
