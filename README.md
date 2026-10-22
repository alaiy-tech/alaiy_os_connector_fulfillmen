# Alaiy OS Connector: Fulfillmen

Reads from the Fulfillmen WMS Open API and keeps what it learns in its own
records. By default it is read only. Inbound and outbound orders can also be
created and cancelled at Fulfillmen on demand (see below), but only after **Allow
creating and cancelling orders** is turned on in the settings. The connector creates **no
Purchase Order, Delivery Note, Sales Invoice or any other ERPNext document**, and
it reads none: it works from the data it is given and keeps results in its own
records. Documents are created later, outside the connector, from the status held
here.

## What it stores

| Record | One per | Holds |
|---|---|---|
| **Fulfillmen Inbound Order** (+ lines table) | inbound order (ASN), named by the ASN number | reference, status and code, warehouse, created and completed time, damaged-box count; per SKU: expected, received QC-passed, received QC-failed, on shelf |
| **Fulfillmen Outbound Order** (+ lines table) | outbound order, named by the order number | customer reference, status and code, shipping service, waybill, created and ship time, tracking status and events; per line: SKU, quantity |
| **Item** (read-only custom fields) | existing Item whose item code = SKU | `fulfillmen_available_stock`, `fulfillmen_shelf_stock`, `fulfillmen_stock_synced_at`, `fulfillmen_registered`, `fulfillmen_barcode`, `fulfillmen_qc_weight/length/width/height` |
| **Fulfillmen Sync Log** | each run | queued / running / success / failed, processed / updated / unmatched / failed counts, notes |
| **Fulfillmen API Log** | each API call | method, path, context, outcome, HTTP status, envelope `Code` and message, duration, query parameters (never the key), the response body in full |
| **Fulfillmen Connector Settings** | single | enable, base URL, API key, warehouse code, webhook secrets, interval, look-back days |

Every API field in the staging records is read only. The one exception is a Link
field on each record (`purchase_order` on the inbound record, `delivery_note` on
the outbound record) for whatever creates the document later to fill in. The
connector never writes it.

Because the staging records are keyed by Fulfillmen's own numbers, nothing depends
on a Purchase Order or Delivery Note existing. `reference_no` carries the
reference given when the order was booked, so the later process can match.

## What it reads

| Need | Fulfillmen call |
|---|---|
| Incoming shipments, status, ordered vs received vs QC | `GET getGRNlist.aspx` |
| Warehouse stock | `GET getinventorylist.aspx` |
| Product registration, QC measurements | `GET GetGoodsList.aspx` |
| Outbound orders and status | `GET GetOrderList.aspx`, `GET GetOrderDetails.aspx` |
| Outbound tracking | `GET GetTrackingInfo.aspx` |
| Connection and warehouse-code check | `GET GetStorageList.aspx` |

The account-info call wants a username and password, which this connector never
stores, so it is not used. Photo links (box and QC images) are signed and expire in
about two hours, so they are not stored.

## Sync

- **Inbound**: every inbound order in a live status (1 not received, 2 received, 3
  QC'd, 4 put away, 10 and 11 first-leg logistics, 12 scanned in). Terminal
  statuses (5 deleted, 6 void, 8 completed) are not polled; a stored record in a
  live status that the sweep no longer returns is re-read by its number, so the
  final state is stored.
- **Outbound**: every order in a live status (3, 4, 5, 11, 12), shipped orders (6)
  created within the look-back window (setting, default 30 days), and any stored
  live record the sweep did not return. Tracking is fetched for shipped orders with
  a waybill and stops once it reads Signed.
- **Stock**: inventory, optionally for one warehouse code; a SKU in several
  warehouses is summed. A SKU that drops out of the list is set to 0, but only when
  the read returned rows, so an empty or wrongly scoped answer never wipes Items.
- **Products**: an Item that drops out of the list is un-registered only when the
  read returned rows.
- A record is written only when a value changed. A timestamp conflict is retried
  once. Status labels are English, taken from the code (the API text is Chinese);
  the raw code is stored too. Dates are normalised to `YYYY-MM-DD HH:MM:SS`; the API
  states no timezone, so none is applied. SKUs are trimmed (the API pads some).
- Interval (one setting, all syncs): Disabled / 5 / 15 / 30 / 60 minutes. Manual
  triggers: `api.sync.trigger_inbound_sync`, `trigger_stock_sync`,
  `trigger_products_sync`, `trigger_outbound_sync`; the first two are on the
  connector card.

## Outbound orders: create, cancel, track

Off until **Allow creating and cancelling orders** is set (and **Enable Fulfillmen**).
The same switch covers the inbound create and cancel of the clone below. Settings used: Customer ID, Default Shipping Service Code, Order Style (1 warehouse
order, which also uses **Warehouse Code**; 2 ordinary order) and Status When Created
(Draft by default: Fulfillmen holds a draft until it is confirmed; Confirmed makes
Fulfillmen start fulfilling it).

| Call (`api.outbound.`) | Fulfillmen call | Does |
|---|---|---|
| `create_outbound_order(order, confirm)` | `POST CreateOrder.aspx` | Creates an order from the data given and stores it in Fulfillmen Outbound Order. `confirm` 1 sends it confirmed, 0 as a draft, empty uses the setting. |
| `cancel_outbound_order(order_no)` | `POST InterceptOrder.aspx` | Cancels by order number or waybill, then re-reads the order. |
| `track_outbound_order(order_no, tracking_no)` | `GET GetOrderDetails.aspx`, `GetTrackingInfo.aspx` | Reads one order of the account by order number or waybill, stores it, returns status, waybill and tracking events. Read only. |
| `list_shipping_services()` | `GET GetShippingList.aspx` | Valid shipping service codes. |
| `list_warehouses()` | `GET GetStorageList.aspx` | Valid warehouse codes. |

All five are for System Manager. The order passed to `create_outbound_order` is a JSON
object (keys in `fulfillmen/order_payload.py`): `reference_no` (required, sent as
CsRefNo), `shipping_code`, `ship_to` (`name`, `country`, `state`, `city`, `address1`
required; `phone`, `mobile`, `email`, `company`, `area`, `address2`, `house_no`, `zip`
optional), `items` (each `sku`, `quantity`, `weight` in kg per unit, `price`,
`currency` USD, GBP or EUR required) and optional `tracking_no`, `remark`, `cod_type`,
`cod_amount`, `ioss`, `vat_no`, `id_card_no`, `weight`, `length`, `width`, `height`.
Every problem found is returned together before anything is sent.

A repeated `reference_no` is safe: Fulfillmen rejects it (code 108), and the connector
finds the existing order by that reference, stores it and returns it with
`duplicate: true`. A create or cancel is retried on a network error or 5xx only
because of that reference rule. Status and tracking of a created order are then kept
current by the outbound sync and the webhook like any other order; a stored draft is
re-read by number until it leaves the draft status.

## Exact API clone: `api.wms`

The Fulfillmen calls for products (read), inbound, stock, warehouses and outbound
orders are available as whitelisted methods with the same fields in and the same
reply out (System Manager). The request
is passed through as given and Fulfillmen's reply comes back unchanged, success or
failure, so anything written against the Fulfillmen docs works against these as it is.
Query fields are arguments; a POST body is the `body` argument (JSON object or its
text). The connector adds the API key and ignores any `Key` it is handed.

Path prefix: `alaiy_os_connector_fulfillmen.api.wms.`

| Method | Fulfillmen call | Docs | Changes data at Fulfillmen |
|---|---|---|---|
| `get_goods_list(SKU, Barcode, Page, page)` | `GET GetGoodsList.aspx` (product list, 50 per page) | 03 | no |
| `create_asn(body)` | `POST CreateASN.aspx` (create inbound order) | 04 | yes |
| `get_grn_list(ASNNumber, StartDate, EndDate, SKU, ReferenceNo, ASNStatus, page, pageSize)` | `GET getGRNlist.aspx` (inbound order query) | 05 | no |
| `cancel_asn(CustomerID, body)` | `POST CancelASN.aspx` (cancel inbound order) | 06 | yes |
| `create_order(body)` | `POST CreateOrder.aspx` | 07 | yes |
| `get_order_list(OrderStatus, OrderNo, TrackingNo, CsRefNo, StartTime, EndTime, page)` | `GET GetOrderList.aspx` | 08 | no |
| `get_order_details(OrderNo, TrackingNo)` | `GET GetOrderDetails.aspx` | 09 | no |
| `intercept_order(body)` | `POST InterceptOrder.aspx` (cancel) | 10 | yes |
| `upload_label(body)` | `POST UploadLabel.aspx` | 11 | yes |
| `get_label_pdf(body)` | `POST GetLabelPDF.aspx` | 12 | no |
| `get_tracking_info(No)` | `GET GetTrackingInfo.aspx` | 13 | no |
| `get_price(body)` | `POST GetPrice.aspx` (freight quote) | 14 | no |
| `get_inventory_list(Storage, SKU, page)` | `GET getinventorylist.aspx` | 15 | no |
| `get_country_list()` | `GET GetCountryList.aspx` | 29 | no |
| `get_shipping_list()` | `GET GetShippingList.aspx` | 30 | no |
| `get_storage_list()` | `GET GetStorageList.aspx` | 31 | no |

The calls that change data (marked yes) are refused until **Allow creating and
cancelling orders** is set. A failure reply (for example code 108, repeated customer reference)
is returned as Fulfillmen sent it; only a transport problem (HTTP error, not JSON)
raises. Reads are retried on network errors and 5xx; an outbound create is retried only
when it carries a `CsRefNo`, an inbound create is sent once, and a cancel and a label
upload are retried because repeating them changes nothing.

After a successful outbound create the order is saved in **Fulfillmen Outbound Order**
(a draft is then re-read by the outbound sync until it leaves the draft status); after
a successful outbound cancel the order is re-read, and after an inbound create or
cancel the inbound order is re-read into **Fulfillmen Inbound Order**, so status stays
current. A failure while saving a record never changes the reply. Product creation, bills, shop
orders, custom orders and the other Fulfillmen calls are not cloned. `api.outbound`
(create from a simplified order with checks, cancel, track) stays as a second way in.
Every call, reads and writes, is written to **Fulfillmen API Log** (query only; a
POST body is never logged).

## On-demand reads

For a screen that should show what the warehouse says now rather than what the
last sweep stored:

- `api.inventory.list_inventory(sku, storage, page)` — one page of
  `getinventorylist.aspx`, 20 rows (the API's own fixed size). `sku` and
  `storage` are filters; omitting `storage` falls back to the configured
  Warehouse Code, so a screen and the sweep cannot be scoped differently by
  accident. Returns `rows` (`sku`, `barcode`, `available`, `on_hand`), the
  `warehouse` the page was read for, and `has_more`.
- `api.inventory.list_warehouses()` — the account's warehouse codes, for a
  picker.

Both check `read` permission on Item and return their failure in an `error`
field instead of raising: an empty table and an unreachable warehouse are
different answers, and a caller that cannot tell them apart reports "no stock"
for an outage. Neither can be called from a browser directly — the API key is a
URL query parameter, so the call only ever happens server-side.

Both are thin wrappers. The calls themselves are `fulfillmen/stock.py`'s
`read_page` and `warehouse_codes`, next to the sweep that walks the same
endpoint, and the row mapping is `util.inventory_row` — so the path, the page
size and the meaning of the two quantities are written down once and the sweep
and these reads cannot drift apart.

Without a warehouse code the read spans every warehouse, and the response
carries no warehouse field, so a SKU held in two of them comes back as two rows
that cannot be told apart. They are returned as given rather than summed:
summing across a paged read would add up halves of two different pages. The
scheduled sweep does sum, because it reads every page before writing.

## Webhook (optional)

Give Fulfillmen `https://<site>/api/method/alaiy_os_connector_fulfillmen.api.webhook.receive`
and set the App Key (and optionally Access Token and Customer Code) in the
settings. The endpoint rejects any request whose headers do not match, answers HTTP
200 immediately, and processes in the background. A notification is never used as
data; it only triggers a re-read through the authenticated API of the inbound order
(type 3), SKU (type 2) or outbound order (type 1) it names.

## Auth and safety

- The customer API key goes in the `Key` query parameter of every request. There
  is no secret and nothing is signed, so the key is the whole credential. It is
  read from the `fulfillmen_api_key` Password field, falling back to the site's
  `site_config.json`. A site that already holds this account key under another
  name, for one of the vendor's other APIs, sets
  `"fulfillmen_api_key_config": "<that key's name>"` and the connector reads it
  from there — so the site keeps one copy of the secret rather than a second one
  that goes stale the first time the original is rotated. Otherwise the
  connector looks for `fulfillmen_api_key` in `site_config.json` directly.
  Either fallback is read through `frappe.conf` and never written to the
  database. Because it is part of the URL, every
  error raised from the HTTP layer is rewritten without the key (also in its
  URL-encoded forms) and raised without its cause chain, so it cannot reach the
  Error Log or Sync Log.
- Base URL must be https (checked on save and again on every request).
- Timeout 30 s; connection errors and 5xx are retried 3 times with backoff; an
  API-level failure (`Code` other than `100`) is not retried.
- Paging stops on a short page; the API's `count` field is not relied on.

## API call log

Every call writes one **Fulfillmen API Log** row — path, context, outcome, HTTP
status, the envelope `Code` and message, duration and the response body in
full. Written from `FulfillmenClient.get`, which is the only way out to the
API, so a new caller is logged without having to remember to be. One row per
call rather than per attempt; the duration covers any retries.

**The key is never stored.** This API takes it as a query parameter, so the
parameters are the one place a secret could reach a log table: `Key` is dropped
by name before the row is built, and every text field on the row is redacted by
value afterwards, which also catches a response that echoed the request URL —
and matters more now that the body is kept whole, since the key could sit
anywhere in it.

Rows go out on their own database connection, committed immediately. Writing
through the caller's transaction would mean either committing a half-finished
sweep or losing the row to the caller's rollback — and a rolled-back call is
usually the one worth having a row for. A failure to log is logged to the Error
Log and never fails the call it was describing.

Retention is 30 days, via frappe's Log Settings. The controller implements
`clear_old_logs` because Log Settings silently ignores a doctype that does not,
which is how a log table ends up unbounded.

## What it cannot see

- The supplier's own courier tracking number and expected arrival date: the inbound
  read does not return them. A shipment is visible once it exists as an inbound order.
- Shipments nobody registered as an inbound order.
- When Fulfillmen deducts its own stock for an outbound order: not documented. Stock
  comes from the inventory read, never from order status.
- Outbound status codes: the order docs and the webhook docs use different tables
  for some of the same numbers. Labels are applied only to codes read from Order
  Details; the raw code is always stored.

## Tests

`python -m unittest alaiy_os_connector_fulfillmen.tests.test_util alaiy_os_connector_fulfillmen.tests.test_webhook alaiy_os_connector_fulfillmen.tests.test_api_log`
(pure helpers, no bench needed).
