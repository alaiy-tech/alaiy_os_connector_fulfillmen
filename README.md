# Alaiy OS Connector: Fulfillmen

Reads from the Fulfillmen WMS Open API and keeps what it learns in its own
records. It is read only: nothing is created, changed or cancelled in Fulfillmen,
and the connector creates **no Purchase Order, Delivery Note, Sales Invoice or any
other ERPNext document**. Those are created later, outside the connector, from the
status held here.

## What it stores

| Record | One per | Holds |
|---|---|---|
| **Fulfillmen Inbound Order** (+ lines table) | inbound order (ASN), named by the ASN number | reference, status and code, warehouse, created and completed time, damaged-box count; per SKU: expected, received QC-passed, received QC-failed, on shelf |
| **Fulfillmen Outbound Order** (+ lines table) | outbound order, named by the order number | customer reference, status and code, shipping service, waybill, created and ship time, tracking status and events; per line: SKU, quantity |
| **Item** (read-only custom fields) | existing Item whose item code = SKU | `fulfillmen_available_stock`, `fulfillmen_shelf_stock`, `fulfillmen_stock_synced_at`, `fulfillmen_registered`, `fulfillmen_barcode`, `fulfillmen_qc_weight/length/width/height` |
| **Fulfillmen Sync Log** | each run | queued / running / success / failed, processed / updated / unmatched / failed counts, notes |
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

- The customer API key goes in the `Key` query parameter of every request. It is
  stored in a Password field and trimmed. Because it is part of the URL, every
  error raised from the HTTP layer is rewritten without the key (also in its
  URL-encoded forms) and raised without its cause chain, so it cannot reach the
  Error Log or Sync Log.
- Base URL must be https (checked on save and again on every request).
- Timeout 30 s; connection errors and 5xx are retried 3 times with backoff; an
  API-level failure (`Code` other than `100`) is not retried.
- Paging stops on a short page; the API's `count` field is not relied on.

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

`python -m unittest alaiy_os_connector_fulfillmen.tests.test_util alaiy_os_connector_fulfillmen.tests.test_webhook`
(pure helpers, no bench needed).
