# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FulfillmenConnectorSettings(Document):
    def validate(self):
        if self.fulfillmen_base_url and not self.fulfillmen_base_url.strip().lower().startswith("https://"):
            frappe.throw("Base URL must start with https:// -- the API key is sent in the request URL.")
        # The last-committed value, so the comparison has to run before the save
        # overwrites it. Setup runs only on the 0 -> 1 transition.
        old_enabled = frappe.db.get_single_value("Fulfillmen Connector Settings", "is_enabled") or 0
        self.flags.fulfillmen_just_enabled = bool(self.is_enabled and not old_enabled)
        self._sync_registry_is_enabled()

    def on_update(self):
        if self.flags.fulfillmen_just_enabled:
            from alaiy_os_connector_fulfillmen.setup.install import setup_custom_fields
            setup_custom_fields()

    def _sync_registry_is_enabled(self):
        if frappe.db.exists("OS Connector Registry", "fulfillmen"):
            frappe.db.set_value("OS Connector Registry", "fulfillmen", "is_enabled", self.is_enabled)
