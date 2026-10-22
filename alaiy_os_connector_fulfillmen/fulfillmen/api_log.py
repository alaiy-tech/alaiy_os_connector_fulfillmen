# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
One Fulfillmen API Log row per call, written best-effort.

Logging never raises into a call and never fails one: a connector that stopped
syncing because it could not write its own audit row would be worse than one
with a gap in the audit.

## The key is never stored

This API takes the customer key as a *query parameter*, so the parameters are
the one place a secret can leak into a log table. `Key` is dropped before the
row is built, and the serialised text is run through `redact` afterwards in
case the value reached it by another route -- the same belt-and-braces the HTTP
errors in client.py already get.

## Why a separate connection

Writing through `frappe.db` would force a choice between two wrong things:

  * commit, and the caller's half-finished work goes with it -- a sweep is one
    transaction across many documents, and committing mid-sweep publishes a
    partly-updated set;
  * do not commit, and the caller's rollback erases the row -- which loses
    exactly the rows worth having, since a failed call is the one most likely
    to be rolled back.

So the row goes out on a connection of its own, committed and closed on the
spot. It is not cached between calls: a worker serves several sites, and a
module-level handle either leaks rows across them or goes stale and starts
failing quietly.
"""

import json
import time

import frappe

from alaiy_os_connector_fulfillmen.fulfillmen.util import redact

DOCTYPE = "Fulfillmen API Log"
_TABLE = "tabFulfillmen API Log"

# The response is stored whole. A truncated body is the one that cuts off just
# before the part that explains the failure, and these responses are bounded by
# the API anyway -- it pages at 20 to 50 rows, so there is no unbounded answer
# to guard against. The column is Long Text.
#
# The envelope message stays capped: it is a Small Text shown in a list view,
# and a vendor that returns a wall of text there should not push the row width
# around. The whole of it is in the body alongside.
_MAX_MESSAGE = 500

SUCCESS_CODE = "100"

# Endpoint file name -> the Context a person filters the list by. Derived from
# the path rather than passed in, so a new call site cannot forget to label
# itself; an unmapped path is "other" rather than a crash.
_CONTEXTS = {
    "getinventorylist.aspx": "inventory",
    "getstoragelist.aspx": "storage_list",
    "getgoodslist.aspx": "products",
    "getgrnlist.aspx": "inbound",
    "getorderlist.aspx": "outbound",
    "getorderdetails.aspx": "order_detail",
    "gettrackinginfo.aspx": "tracking",
    "createorder.aspx": "outbound",
    "interceptorder.aspx": "outbound",
    "uploadlabel.aspx": "outbound",
    "getlabelpdf.aspx": "outbound",
    "createasn.aspx": "inbound",
    "cancelasn.aspx": "inbound",
}


def context_for(path):
    return _CONTEXTS.get(str(path or "").rsplit("/", 1)[-1].lower(), "other")


def safe_params(params, key):
    """The query as JSON, with the API key gone.

    Dropped by name first -- the parameter this API authenticates with -- then
    redacted by value, which also catches a key that turned up in a filter
    someone passed by mistake.
    """
    shown = {k: v for k, v in (params or {}).items() if k.lower() != "key"}
    return redact(json.dumps(shown, sort_keys=True, default=str), key)


def _row(path, params, key, started, resp=None, data=None, error=None, method="GET"):
    """The log row for one call, whatever happened to it."""
    status = int(getattr(resp, "status_code", 0) or 0)

    api_code = api_message = None
    if isinstance(data, dict):
        code = data.get("Code") or data.get("code")
        api_code = None if code is None else str(code)
        api_message = (
            data.get("Enmessage") or data.get("enmessage") or data.get("message") or None
        )

    # A 200 carrying a Code other than 100 is still a failure: the envelope is
    # the real verdict, which is why client.get() raises on it.
    failed = error is not None or not (200 <= status < 300)
    if not failed and isinstance(data, dict):
        failed = api_code not in (None, SUCCESS_CODE)
    if error is not None:
        api_message = f"{type(error).__name__}: {error}"

    body = getattr(resp, "text", "") or ""

    return {
        "method": method,
        "path": str(path),
        "context": context_for(path),
        "outcome": "Failed" if failed else "Success",
        "status_code": status,
        "api_code": api_code,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "query_params": safe_params(params, key),
        "api_message": redact(str(api_message), key)[:_MAX_MESSAGE] if api_message else None,
        "response_excerpt": redact(body, key),
    }


def _write(row):
    """INSERT one row on its own connection, commit, close. See the module docstring."""
    from frappe.database import get_db
    from frappe.model.naming import make_autoname

    conf = frappe.local.conf
    row = dict(row, name=make_autoname("hash", DOCTYPE), creation=frappe.utils.now(),
               modified=frappe.utils.now(), owner="Administrator", modified_by="Administrator")
    columns = ", ".join(f"`{c}`" for c in row)
    placeholders = ", ".join(["%s"] * len(row))

    conn = get_db(socket=conf.db_socket, host=conf.db_host, port=conf.db_port,
                  user=conf.db_user or conf.db_name, password=conf.db_password,
                  cur_db_name=conf.db_name)
    try:
        conn.sql(f"INSERT INTO `{_TABLE}` ({columns}) VALUES ({placeholders})", tuple(row.values()))
        conn.commit()
    finally:
        conn.close()


def record(path, params, key, started, resp=None, data=None, error=None, method="GET"):
    """Log one call. Never raises, never fails the call it is describing."""
    try:
        # Imported without a site (a plain python shell, the pure unit tests):
        # there is nothing to write to, and that is not an error.
        if not getattr(frappe.local, "conf", None):
            return
        _write(_row(path, params, key, started, resp=resp, data=data, error=error, method=method))
    except Exception:
        try:
            frappe.log_error(title="Fulfillmen API Log write failed", message=frappe.get_traceback())
        except Exception:
            pass
