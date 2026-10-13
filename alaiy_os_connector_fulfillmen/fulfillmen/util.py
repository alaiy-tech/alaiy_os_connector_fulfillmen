# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Pure helpers with no Frappe dependency, so they can be checked with plain
`python -m unittest` (see tests/test_util.py).
"""

import hmac
import re
from urllib.parse import quote, quote_plus

# Inbound order (ASN) status codes (ASN Query and inbound webhook docs).
# Terminal states never change again, so they are not polled.
ASN_STATUS = {
    "0": "Draft", "1": "Not Received", "2": "Received", "3": "QC Done", "4": "Put Away",
    "5": "Deleted", "6": "Void", "8": "Completed",
    "10": "First-Leg Logistics In", "11": "First-Leg Logistics Out", "12": "Scanned In",
}
TERMINAL_ASN_STATUSES = {"5", "6", "8"}
POLLED_ASN_STATUSES = ["1", "2", "3", "4", "10", "11", "12"]

# Outbound order status codes as given by Order Query / Order Details. The
# webhook documentation uses a different table for some of the same numbers, so
# these labels are only ever applied to codes read from Order Details.
ORDER_STATUS = {
    "1": "Draft", "3": "Confirmed", "4": "Paid, Pending Delivery", "5": "Unpaid, Pending Delivery",
    "6": "Shipped", "8": "Deleted", "11": "Processing", "12": "Out of Stock",
}
POLLED_ORDER_STATUSES = ["3", "4", "5", "11", "12"]   # in progress; shipped (6) is polled in a date window
SHIPPED_ORDER_STATUS = "6"
DELETED_ORDER_STATUS = "8"

# GetTrackingInfo "Status" codes.
TRACKING_STATUS = {
    "0": "In Transit", "1": "Querying", "2": "Delivery Failed", "3": "Signed",
    "4": "Possibly Abnormal", "5": "Arrived, Awaiting Pickup", "6": "In Transit Too Long",
    "7": "Not Found",
}
TRACKING_DONE = {"3"}   # signed for: tracking is no longer refreshed


def redact(text, *secrets):
    """Remove every non-empty secret from text, also in the URL-encoded forms an
    HTTP library may print. The API takes the key as a URL query parameter, so
    exception messages from the HTTP layer contain it."""
    text = str(text)
    for secret in secrets:
        if not secret:
            continue
        for form in {secret, quote(secret, safe=""), quote_plus(secret)}:
            text = text.replace(form, "***")
    return text


def clean(value):
    """Strip a string value; the API pads some codes ("6925925700115 ")."""
    return str(value or "").strip()


def to_datetime(value):
    """Normalise the API's date text ("2026/10/12 10:00:00", "2026-10-12 10:00:00",
    "2026/4/8 17:27:37") to "YYYY-MM-DD HH:MM:SS" for a Datetime field; None when
    empty or not a date. The API states no timezone, so none is applied."""
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", clean(value))
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x or 0) for x in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31 and h < 24 and mi < 60 and s < 60):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"


def to_number(value, default=0):
    """The API returns numbers as strings ("20", "", None). Parse defensively."""
    try:
        n = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return int(n) if n.is_integer() else n


def split_across(total, caps):
    """Spread `total` over lines in order, each taking at most its cap; the last
    line takes any remainder. Used when one SKU appears on several PO lines."""
    out, left = [], total
    for i, cap in enumerate(caps):
        take = left if i == len(caps) - 1 else min(left, cap)
        out.append(take)
        left -= take
    return out


def verify_webhook(headers, app_key, access_token=None, customer_code=None):
    """True when the request carries the configured credentials. App-Key is
    mandatory; Access-Token and X-Customer-Code are checked only when
    configured. Constant-time comparison."""
    def same(got, want):
        return hmac.compare_digest(str(got or "").encode(), str(want).encode())

    if not app_key or not same(headers.get("App-Key"), app_key):
        return False
    if access_token and not same(headers.get("Access-Token"), access_token):
        return False
    if customer_code and not same(headers.get("X-Customer-Code"), customer_code):
        return False
    return True


def events_text(events):
    """Tracking events as plain lines, "time  description", in the order given."""
    return "\n".join(f"{e.get('OccurTime', '')}  {e.get('DetailDesc', '')}".strip() for e in events or [])
