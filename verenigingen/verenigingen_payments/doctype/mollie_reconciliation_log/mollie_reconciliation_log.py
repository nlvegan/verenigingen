# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MollieReconciliationLog(Document):
    """
    Mollie Reconciliation Log

    Stores the results of automated daily reconciliation runs between
    Mollie settlements/balance transactions and Frappe Bank Transactions.

    Used by ReconciliationEngine to maintain audit trail of reconciliation
    operations, errors, warnings, and corrections.
    """

    def validate(self):
        """Validate reconciliation log fields"""
        # Ensure counts are non-negative
        if self.error_count < 0:
            frappe.throw("Error count cannot be negative")
        if self.warning_count < 0:
            frappe.throw("Warning count cannot be negative")
        if self.correction_count < 0:
            frappe.throw("Correction count cannot be negative")

    def on_submit(self):
        """Not submittable - reconciliation logs are informational only"""
        pass
