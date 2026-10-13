"""
Single source of truth for this connector's registration metadata.
Consumed by setup/install.py -> upserted into alaiy_os's OS Connector Registry.
"""

connector_meta = {
    "connector_id": "fulfillmen",
    "connector_name": "Fulfillmen",
    "connector_app": "alaiy_os_connector_fulfillmen",
    # A warehouse partner neither sells to nor supplies the business;
    # "supplier" is the closest existing registry bucket (goods come in from it).
    "connector_type": "supplier",
    "description": "Fulfillmen WMS connector -- reads incoming shipments, received and QC quantities, outbound orders with tracking, products and warehouse stock into its own records. Read only; creates no ERPNext documents.",
    "icon": "box",
    "icon_url": "",
    "settings_doctype": "Fulfillmen Connector Settings",
    "test_method": "alaiy_os_connector_fulfillmen.api.test_connection.test_connection",
    # The registry exposes two sync "slots"; map them to this connector's two pulls.
    "sync_categories_method": "alaiy_os_connector_fulfillmen.api.sync.trigger_inbound_sync",
    "sync_items_method": "alaiy_os_connector_fulfillmen.api.sync.trigger_stock_sync",
    "sync_status_method": "alaiy_os_connector_fulfillmen.api.sync.get_sync_status",
    "sync_categories_label": "Inbound",
    "sync_items_label": "Stock",
    "is_enabled": 0,
    "connection_status": "untested",
}
