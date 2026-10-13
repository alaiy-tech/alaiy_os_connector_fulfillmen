app_name = "alaiy_os_connector_fulfillmen"
app_title = "Alaiy Os Connector Fulfillmen"
app_publisher = "Alaiy"
app_description = "Fulfillmen WMS connector for AlaiyOS"
app_email = "mail@alaiy.com"
app_license = "agpl-3.0"

# Every Alaiy OS connector runs on top of alaiy_os (registry, workspace,
# connector card) and erpnext (Item, and the Link targets on the staging records).
required_apps = ["alaiy_os", "erpnext"]

after_install = [
    "alaiy_os_connector_fulfillmen.setup.install.after_install"
]

after_migrate = [
    "alaiy_os_connector_fulfillmen.setup.install.sync_connector_registry"
]

# Register this connector's Sync Log under the Alaiy OS "Logs" sidebar section.
alaiy_os_sidebar_log_items = [
    {
        "link_type": "DocType",
        "link_to": "Fulfillmen Sync Log",
        "label": "Fulfillmen Logs",
        "icon": "activity",
    }
]

# Runs every minute; check_and_enqueue() decides whether a sync is actually due
# from the interval configured in Fulfillmen Connector Settings.
scheduler_events = {
    "cron": {
        "* * * * *": [
            "alaiy_os_connector_fulfillmen.fulfillmen.sync_jobs.check_and_enqueue"
        ]
    }
}
