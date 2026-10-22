# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Exact clone of the Fulfillmen API for products (read), inbound, stock, warehouses
and outbound orders, as whitelisted methods.

Path prefix: alaiy_os_connector_fulfillmen.api.wms.<name>

Same fields in, same reply out as the Fulfillmen docs (docs/fulfillmen/03 to 15
and 29 to 31); see fulfillmen/wms.py. Query fields are arguments; a POST body is
the `body` argument (a JSON object or its text). Role: System Manager.
Creating or cancelling an inbound or outbound order and uploading a label are
refused until "Allow creating and cancelling orders" is set in the settings.
"""

import frappe

from alaiy_os_connector_fulfillmen.fulfillmen.client import FulfillmenAPIError
from alaiy_os_connector_fulfillmen.fulfillmen.wms import call

_ROLES = ("System Manager",)


def _run(name, params=None, body=None):
    frappe.only_for(_ROLES)
    if isinstance(body, str):
        body = frappe.parse_json(body)
    try:
        return call(name, params, body)
    except FulfillmenAPIError as e:
        frappe.throw(str(e))


@frappe.whitelist()
def get_goods_list(SKU=None, Barcode=None, Page=None, page=None):
    """GET GetGoodsList.aspx (50 per page). The docs name the page field `Page` in the
    table and `page` in the example; send whichever you give."""
    return _run("get_goods_list", dict(SKU=SKU, Barcode=Barcode, Page=Page, page=page))


@frappe.whitelist()
def create_asn(body):
    """POST CreateASN.aspx (create inbound order). Body fields as in the docs:
    ASNStatus (0 draft, 1 not received), Type, Style, CustomerID, WarehouseCode,
    DeliveryStyle, WaybillNumber, ReachStartTime, ReferenceNo, OrderNo,
    ASNDetail[{SKU, Quantity, Boxno, WaybillNo}]."""
    return _run("create_asn", body=body)


@frappe.whitelist()
def get_grn_list(ASNNumber=None, StartDate=None, EndDate=None, SKU=None, ReferenceNo=None, ASNStatus=None, page=None, pageSize=None):
    """GET getGRNlist.aspx (inbound order query; default 20 per page, at most 100)."""
    return _run("get_grn_list", dict(
        ASNNumber=ASNNumber, StartDate=StartDate, EndDate=EndDate, SKU=SKU,
        ReferenceNo=ReferenceNo, ASNStatus=ASNStatus, page=page, pageSize=pageSize,
    ))


@frappe.whitelist()
def cancel_asn(CustomerID, body):
    """POST CancelASN.aspx?CustomerID=... (cancel inbound order). Body: {"ASNNumber": ...}."""
    return _run("cancel_asn", dict(CustomerID=CustomerID), body=body)


@frappe.whitelist()
def create_order(body):
    """POST CreateOrder.aspx. Body fields as in the docs: Style, CustomerID,
    ShippingCode, ShipTo*, OrderStatus (1 draft, 3 confirmed), CsRefNo,
    WarehouseId, Products[...]."""
    return _run("create_order", body=body)


@frappe.whitelist()
def get_order_list(OrderStatus=None, OrderNo=None, TrackingNo=None, CsRefNo=None, StartTime=None, EndTime=None, page=None):
    """GET GetOrderList.aspx (20 per page)."""
    return _run("get_order_list", dict(
        OrderStatus=OrderStatus, OrderNo=OrderNo, TrackingNo=TrackingNo, CsRefNo=CsRefNo,
        StartTime=StartTime, EndTime=EndTime, page=page,
    ))


@frappe.whitelist()
def get_order_details(OrderNo=None, TrackingNo=None):
    """GET GetOrderDetails.aspx."""
    return _run("get_order_details", dict(OrderNo=OrderNo, TrackingNo=TrackingNo))


@frappe.whitelist()
def intercept_order(body):
    """POST InterceptOrder.aspx (order cancel). Body: {"OrderNo": ...}."""
    return _run("intercept_order", body=body)


@frappe.whitelist()
def upload_label(body):
    """POST UploadLabel.aspx. Body: {"TrackingNo": ..., "Url": <PDF link>}."""
    return _run("upload_label", body=body)


@frappe.whitelist()
def get_label_pdf(body):
    """POST GetLabelPDF.aspx. Body: {"OrderNo": ..., "Type": "0" or "1"}."""
    return _run("get_label_pdf", body=body)


@frappe.whitelist()
def get_tracking_info(No=None):
    """GET GetTrackingInfo.aspx. `No`: system order number, waybill or transfer number."""
    return _run("get_tracking_info", dict(No=No))


@frappe.whitelist()
def get_price(body):
    """POST GetPrice.aspx (freight quote). Body: Type, ShortName, Country, CusCode,
    ZipCode, states, Weight, Volume, Minimum."""
    return _run("get_price", body=body)


@frappe.whitelist()
def get_inventory_list(Storage=None, SKU=None, page=None):
    """GET getinventorylist.aspx (20 per page)."""
    return _run("get_inventory_list", dict(Storage=Storage, SKU=SKU, page=page))


@frappe.whitelist()
def get_country_list():
    """GET GetCountryList.aspx."""
    return _run("get_country_list")


@frappe.whitelist()
def get_shipping_list():
    """GET GetShippingList.aspx."""
    return _run("get_shipping_list")


@frappe.whitelist()
def get_storage_list():
    """GET GetStorageList.aspx."""
    return _run("get_storage_list")
