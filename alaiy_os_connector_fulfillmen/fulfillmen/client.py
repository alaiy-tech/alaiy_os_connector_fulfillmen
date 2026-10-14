# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
HTTP client for the Fulfillmen WMS Open API. Read-only: every call is a GET.

Auth: the customer API key (User Center, My Information, API interface) goes in
the `Key` query parameter of every request, from the connector's settings or,
failing that, from the site's own config -- see `_api_key`. There is no token
exchange and no secret: this API signs nothing, so an access key is the whole
credential. Because
the key is part of the URL, every error raised from here is rewritten without
it and raised `from None`, so neither the message nor the exception chain (and
therefore neither the Error Log nor the Sync Log) can contain the key.

Every response carries success ("success"/"failure") and Code ("100" = success).
HTTP-level problems and 5xx are retried with backoff; an API-level failure
(Code other than 100) is a real answer and is not retried.
"""

import time

import frappe
import requests

from alaiy_os_connector_fulfillmen.fulfillmen.util import redact

DEFAULT_BASE_URL = "https://wms.fulfillmen.com"
TIMEOUT_SECONDS = 30
_ATTEMPTS = 3
_MAX_PAGES = 500   # safety stop against a server that never returns an empty page

# site_config.json keys. The first holds the customer API key; the second names
# a *different* site_config key to read it from instead. See _api_key.
SITE_CONFIG_KEY = "fulfillmen_api_key"
SITE_CONFIG_KEY_ALIAS = "fulfillmen_api_key_config"


def _api_key(settings):
    """The customer API key: the settings field, else the site's own config.

    The settings field wins, so a connector configured through the Desk behaves
    exactly as before.

    The site_config fallback exists because the same account key is often
    already on the site under another name, held for one of this vendor's other
    APIs. Copying it into a second place would make a credential that goes stale
    the first time the original is rotated -- silently, because the connector
    keeps answering with the old one until a call fails. So a site that already
    has it points at it with `fulfillmen_api_key_config` rather than repeating
    the value, and there is still exactly one copy of the secret on the site.

    Read through frappe.conf either way: a value the connector only reads never
    enters the database, a fixture or a backup of one.
    """
    stored = (settings.get_password("fulfillmen_api_key", raise_exception=False) or "").strip()
    if stored:
        return stored
    alias = str(frappe.conf.get(SITE_CONFIG_KEY_ALIAS) or "").strip()
    return str(frappe.conf.get(alias or SITE_CONFIG_KEY) or "").strip()


class FulfillmenAPIError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class FulfillmenClient:
    def __init__(self):
        settings = frappe.get_single("Fulfillmen Connector Settings")
        self.key = _api_key(settings)
        if not self.key:
            raise FulfillmenAPIError(
                f"API Key is not set, in the settings or as {SITE_CONFIG_KEY} in site_config.json."
            )
        self.base_url = (settings.fulfillmen_base_url or DEFAULT_BASE_URL).rstrip("/")
        if not self.base_url.startswith("https://"):
            raise FulfillmenAPIError("Base URL must use https; the API key is sent in the URL.")
        self.storage = (settings.fulfillmen_warehouse_code or "").strip() or None

    def get(self, path, **params):
        params = {k: v for k, v in params.items() if v not in (None, "")}
        params["Key"] = self.key
        last = None
        for attempt in range(_ATTEMPTS):
            if attempt:
                time.sleep(2 ** attempt)
            try:
                resp = requests.get(self.base_url + path, params=params, timeout=TIMEOUT_SECONDS)
            except requests.RequestException as e:
                last = FulfillmenAPIError("Request failed: " + redact(e, self.key))
                continue
            if resp.status_code >= 500:
                last = FulfillmenAPIError(f"HTTP {resp.status_code} from Fulfillmen.", resp.status_code)
                continue
            if resp.status_code != 200:
                raise FulfillmenAPIError(f"HTTP {resp.status_code} from Fulfillmen.", resp.status_code) from None
            try:
                data = resp.json()
            except ValueError:
                raise FulfillmenAPIError("Fulfillmen did not return JSON.", resp.status_code) from None
            if not isinstance(data, dict):
                raise FulfillmenAPIError("Unexpected Fulfillmen response shape.", resp.status_code) from None
            code = str(data.get("Code") or data.get("code") or "")
            if code != "100":
                msg = data.get("Enmessage") or data.get("enmessage") or data.get("message") or "request failed"
                raise FulfillmenAPIError(redact(f"Fulfillmen error {code or '?'}: {msg}", self.key)) from None
            return data
        raise last from None

    def pages(self, path, page_param, page_size, **params):
        """Yield every row of a paged list endpoint. A page shorter than
        `page_size` is the last one. The reported `count` is not relied on: the
        docs call it a total but do not guarantee it. Safety cap on pages."""
        for page in range(1, _MAX_PAGES + 1):
            rows = self.get(path, **{page_param: page}, **params).get("data") or []
            yield from rows
            if len(rows) < page_size:
                return
