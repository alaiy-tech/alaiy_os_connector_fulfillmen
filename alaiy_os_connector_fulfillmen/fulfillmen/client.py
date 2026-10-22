# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
HTTP client for the Fulfillmen WMS Open API.

Auth: the customer API key (User Center, My Information, API interface) goes in
the `Key` query parameter of every request. There is no token exchange. Because
the key is part of the URL, every error raised from here is rewritten without
it and raised `from None`, so neither the message nor the exception chain (and
therefore neither the Error Log nor the Sync Log) can contain the key.

Reads are GET. The only writes are the outbound order calls (create, cancel),
sent with `post`. Every response carries success ("success"/"failure") and Code
("100" = success). HTTP-level problems and 5xx are retried with backoff; an
API-level failure (Code other than 100) is a real answer and is not retried.
A POST is retried only when the caller marks it idempotent (the order create
carries a customer reference number that Fulfillmen rejects when repeated).
"""

import time

import frappe
import requests

from alaiy_os_connector_fulfillmen.fulfillmen.util import redact

DEFAULT_BASE_URL = "https://wms.fulfillmen.com"
TIMEOUT_SECONDS = 30
_ATTEMPTS = 3
_MAX_PAGES = 500   # safety stop against a server that never returns an empty page


class FulfillmenAPIError(Exception):
    """`api_code` is the API's own Code (for example "108" for a repeated customer
    reference); `data` is the decoded reply, kept so a caller can read fields the
    message does not carry."""

    def __init__(self, message, status_code=None, api_code=None, data=None):
        super().__init__(message)
        self.status_code = status_code
        self.api_code = api_code
        self.data = data or {}


def _api_message(data):
    """The API puts a useful text in `message` and often a bare "fails" in
    `Enmessage`; prefer the first that says something."""
    for key in ("Enmessage", "enmessage", "message"):
        text = str(data.get(key) or "").strip()
        if text and text.lower() not in ("fails", "fail"):
            return text
    return "request failed"


class FulfillmenClient:
    def __init__(self):
        settings = frappe.get_single("Fulfillmen Connector Settings")
        self.key = (settings.get_password("fulfillmen_api_key", raise_exception=False) or "").strip()
        if not self.key:
            raise FulfillmenAPIError("API Key is not set.")
        self.base_url = (settings.fulfillmen_base_url or DEFAULT_BASE_URL).rstrip("/")
        if not self.base_url.startswith("https://"):
            raise FulfillmenAPIError("Base URL must use https; the API key is sent in the URL.")
        self.storage = (settings.fulfillmen_warehouse_code or "").strip() or None

    def _send(self, method, path, params, json=None, retry=True):
        """HTTP only: retries, JSON decoding, key redaction. Returns the decoded
        reply whatever its Code is."""
        params = {k: v for k, v in params.items() if v not in (None, "")}
        params["Key"] = self.key
        attempts = _ATTEMPTS if retry else 1
        last = None
        for attempt in range(attempts):
            if attempt:
                time.sleep(2 ** attempt)
            try:
                resp = requests.request(method, self.base_url + path, params=params, json=json, timeout=TIMEOUT_SECONDS)
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
            return data, resp.status_code
        raise last from None

    def _call(self, method, path, params, json=None, retry=True):
        data, status = self._send(method, path, params, json, retry)
        code = str(data.get("Code") or data.get("code") or "")
        if code != "100":
            raise FulfillmenAPIError(
                redact(f"Fulfillmen error {code or '?'}: {_api_message(data)}", self.key),
                status, api_code=code, data=data,
            ) from None
        return data

    def send(self, method, path, params=None, body=None, idempotent=False):
        """Raw call for the API clone: returns Fulfillmen's reply exactly as sent,
        success or failure. Only transport problems raise. GET calls are retried;
        a POST only when `idempotent`."""
        retry = True if method == "GET" else idempotent
        return self._send(method, path, dict(params or {}), json=body, retry=retry)[0]

    def get(self, path, **params):
        return self._call("GET", path, params)

    def post(self, path, body, idempotent=False, **params):
        """POST a JSON body. Retried on network errors and 5xx only when
        `idempotent` is true."""
        return self._call("POST", path, params, json=body, retry=idempotent)

    def pages(self, path, page_param, page_size, **params):
        """Yield every row of a paged list endpoint. A page shorter than
        `page_size` is the last one. The reported `count` is not relied on: the
        docs call it a total but do not guarantee it. Safety cap on pages."""
        for page in range(1, _MAX_PAGES + 1):
            rows = self.get(path, **{page_param: page}, **params).get("data") or []
            yield from rows
            if len(rows) < page_size:
                return
