# Copyright (c) 2025, Organisatie Vereniging Veganisme and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PaymentHistoryUpdateQueue(Document):
    """Payment History Update Queue for serialized payment history updates"""

    def validate(self):
        """Validate the queue entry"""
        # Ensure member exists
        if not frappe.db.exists("Member", self.member):
            frappe.throw(f"Member {self.member} does not exist")

        # Ensure invoice exists
        if not frappe.db.exists("Sales Invoice", self.invoice):
            frappe.throw(f"Sales Invoice {self.invoice} does not exist")

        # Validate action
        valid_actions = ["invoice_submitted", "invoice_cancelled", "invoice_updated"]
        if self.action not in valid_actions:
            frappe.throw(f"Action must be one of: {', '.join(valid_actions)}")

    def before_insert(self):
        """Set defaults before inserting"""
        if not self.status:
            self.status = "Pending"
        if not self.retry_count:
            self.retry_count = 0
