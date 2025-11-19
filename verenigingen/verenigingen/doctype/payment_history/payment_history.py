# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PaymentHistory(Document):
    def validate(self):
        """Validate payment history entry for uniqueness and data integrity"""
        self.validate_payment_id_uniqueness()
        self.validate_required_fields()

    def validate_payment_id_uniqueness(self):
        """Ensure payment_id is globally unique across all donations"""
        if not self.payment_id:
            return

        # Check for duplicates in this donation's payment history
        parent_doc = self.get_parent_doc()
        if parent_doc:
            for existing_payment in parent_doc.get("payment_history", []):
                if existing_payment.name != self.name and existing_payment.payment_id == self.payment_id:
                    frappe.throw(f"Payment ID {self.payment_id} already exists in this donation")

        # Check for global uniqueness across all donations
        # This prevents the same Mollie payment from being added to multiple donations
        existing_payments = frappe.db.sql(
            """
            SELECT parent, name
            FROM `tabPayment History`
            WHERE payment_id = %s AND name != %s
        """,
            (self.payment_id, self.name or ""),
        )

        if existing_payments:
            parent_donation = existing_payments[0][0]
            frappe.throw(f"Payment ID {self.payment_id} already exists in donation {parent_donation}")

    def validate_required_fields(self):
        """Validate that required fields have sensible values"""
        if not self.payment_date:
            frappe.throw("Payment Date is required")

        if not self.amount or self.amount <= 0:
            frappe.throw("Payment Amount must be greater than zero")

        if self.payment_status not in ["Open", "Pending", "Completed", "Cancelled", "Error"]:
            frappe.throw(f"Invalid payment status: {self.payment_status}")

    def get_parent_doc(self):
        """Get the parent Donation document"""
        if hasattr(self, "parent") and self.parent:
            return frappe.get_doc("Donation", self.parent)
        return None
