# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WebhookProcessingLog(Document):
    """
    Webhook Processing Log for audit trails and debugging
    """

    def before_insert(self):
        """Set defaults before insert"""
        if not self.processed_at:
            self.processed_at = frappe.utils.now_datetime()
