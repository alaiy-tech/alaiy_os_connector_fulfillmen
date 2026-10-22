# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Pure builder for the CreateOrder request body (no Frappe dependency, see
tests/test_order_payload.py).

The caller passes an order in plain snake_case keys; this module checks it
against the Create Order documentation and maps it to Fulfillmen's own field
names. Nothing here knows about any ERPNext document.

Order (all text unless noted):
  reference_no   required  our reference, sent as CsRefNo. Fulfillmen rejects a
                           repeated one, which makes a retry safe.
  shipping_code  service code; defaults from the settings
  tracking_no, remark, cod_type, cod_amount, ioss, vat_no, id_card_no  optional
  weight, length, width, height  optional parcel measures (kg, cm)
  ship_to        required object: name, country, state, city, address1; optional
                 phone, mobile, email, company, area, address2, house_no, zip
  items          required list; each: sku, quantity (whole number above 0),
                 weight (kg per unit, above 0), price (per unit), currency
                 (USD, GBP or EUR); optional name_en, name_cn, length, width,
                 height, origin, hs_code, material, application, sales_link
"""

STYLE_WAREHOUSE = "1"
STYLE_ORDINARY = "2"
STATUS_DRAFT = 1
STATUS_CONFIRMED = 3
CURRENCIES = ("USD", "GBP", "EUR")

# Maximum lengths from the Create Order documentation.
_SHIP_TO = {
    # key: (API field, required, max length)
    "name": ("ShipToName", True, 100),
    "country": ("ShipToCountry", True, 50),
    "state": ("ShipToState", True, 100),
    "city": ("ShipToCity", True, 100),
    "address1": ("ShipToAdress1", True, 200),   # the API spells it "Adress"
    "phone": ("ShipToPhoneNumber", False, 20),
    "mobile": ("ShipToMobileNumber", False, 20),
    "email": ("ShipToEmail", False, 100),
    "company": ("ShipToCompanyName", False, 200),
    "area": ("ShipToArea", False, 100),
    "address2": ("ShipToAdress2", False, 200),
    "house_no": ("ShipToHouseNo", False, 10),
    "zip": ("ShipToZipCode", False, 50),
}
_OPTIONAL_TOP = {
    "tracking_no": "TrackingNo", "remark": "CusRemark", "cod_type": "CODType", "cod_amount": "CODMoney",
    "ioss": "IOSS", "vat_no": "VATNo", "id_card_no": "IDCardNo",
    "weight": "CustWeight", "length": "FLength", "width": "FWidth", "height": "FHeight",
}
_ITEM_OPTIONAL = {
    "name_en": ("EnName", 200), "name_cn": ("CnName", 200), "length": ("Length", None), "width": ("Width", None),
    "height": ("Height", None), "origin": ("ProducingArea", None), "hs_code": ("HSCode", None),
    "material": ("Material", None), "application": ("Application", None), "sales_link": ("SalesAddress", None),
}


def _text(value):
    return "" if value is None else str(value).strip()


def _number(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def build_create_payload(order, defaults):
    """Return the CreateOrder body. `defaults` carries customer_id,
    shipping_code, style ("1" or "2"), warehouse_code and status (1 or 3).
    Raises ValueError listing every problem found."""
    problems = []
    order = order or {}

    def need(label, value):
        if not _text(value):
            problems.append(f"{label} is required")

    need("customer_id (settings)", defaults.get("customer_id"))
    need("reference_no", order.get("reference_no"))
    shipping_code = _text(order.get("shipping_code")) or _text(defaults.get("shipping_code"))
    need("shipping_code (order or settings)", shipping_code)

    style = _text(defaults.get("style")) or STYLE_WAREHOUSE
    if style not in (STYLE_WAREHOUSE, STYLE_ORDINARY):
        problems.append("style must be 1 (warehouse order) or 2 (ordinary order)")
    if style == STYLE_WAREHOUSE:
        need("warehouse_code (settings), needed for a warehouse order", defaults.get("warehouse_code"))

    payload = {
        "Style": style,
        "CustomerID": _text(defaults.get("customer_id")),
        "ShippingCode": shipping_code,
        "OrderStatus": int(defaults.get("status") or STATUS_DRAFT),
        "CsRefNo": _text(order.get("reference_no")),
    }
    if style == STYLE_WAREHOUSE:
        payload["WarehouseId"] = _text(defaults.get("warehouse_code"))

    ship_to = order.get("ship_to") or {}
    if not isinstance(ship_to, dict):
        problems.append("ship_to must be an object")
        ship_to = {}
    for key, (field, required, limit) in _SHIP_TO.items():
        value = _text(ship_to.get(key))
        if required:
            need(f"ship_to.{key}", value)
        if len(value) > limit:
            problems.append(f"ship_to.{key} is longer than {limit} characters")
        if value:
            payload[field] = value

    for key, field in _OPTIONAL_TOP.items():
        value = _text(order.get(key))
        if value:
            payload[field] = value

    payload["Products"] = _products(order.get("items"), problems)
    if problems:
        raise ValueError("; ".join(problems))
    return payload


def _products(items, problems):
    if not isinstance(items, list) or not items:
        problems.append("items must be a non-empty list")
        return []
    products = []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            problems.append(f"items[{i}] must be an object")
            continue
        label = f"items[{i}]"
        sku = _text(item.get("sku"))
        if not sku:
            problems.append(f"{label}.sku is required")
        elif len(sku) > 50:
            problems.append(f"{label}.sku is longer than 50 characters")

        qty = _number(item.get("quantity"))
        if qty is None or qty <= 0 or qty != int(qty):
            problems.append(f"{label}.quantity must be a whole number above 0")
        weight = _number(item.get("weight"))
        if weight is None or weight <= 0:
            problems.append(f"{label}.weight (kg per unit) must be above 0")
        price = _number(item.get("price"))
        if price is None or price < 0:
            problems.append(f"{label}.price is required and cannot be negative")
        currency = _text(item.get("currency")).upper()
        if currency not in CURRENCIES:
            problems.append(f"{label}.currency must be one of {', '.join(CURRENCIES)}")

        product = {"SKU": sku, "Quantity": int(qty or 0), "Weight": weight, "Price": price, "Currency": currency}
        for key, (field, limit) in _ITEM_OPTIONAL.items():
            value = _text(item.get(key))
            if limit and len(value) > limit:
                problems.append(f"{label}.{key} is longer than {limit} characters")
            if value:
                product[field] = value
        products.append(product)
    return products
