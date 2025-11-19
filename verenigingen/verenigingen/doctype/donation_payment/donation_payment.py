# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class DonationPayment(Document):
    """Child table for tracking payments made for donations"""

    def validate(self):
        """Validate donation payment entry"""
        if self.amount and self.amount <= 0:
            frappe.throw("Payment amount must be greater than zero")

        # Validate required fields for different payment methods
        if self.payment_method == "Mollie":
            if not self.mollie_payment_id:
                frappe.throw("Mollie Payment ID is required for Mollie payments")
