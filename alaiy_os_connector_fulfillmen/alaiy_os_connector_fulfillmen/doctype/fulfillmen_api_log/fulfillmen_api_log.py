# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now


class FulfillmenAPILog(Document):
    @staticmethod
    def clear_old_logs(days=30):
        """Delete rows older than `days`.

        Frappe's Log Settings refuses a doctype whose controller has no
        `clear_old_logs` (see core.doctype.log_settings.LogType), so without
        this method the retention entry in hooks.py would be dropped without a
        word and the table would grow forever.
        """
        table = frappe.qb.DocType("Fulfillmen API Log")
        frappe.db.delete(table, filters=(table.creation < (Now() - Interval(days=days))))
