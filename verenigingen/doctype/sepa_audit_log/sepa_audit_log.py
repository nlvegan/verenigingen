# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SEPAAuditLog(Document):
    """
    SEPA Audit Log DocType

    Stores comprehensive audit trails for all SEPA operations
    and security events with structured data and retention policies.
    """

    def validate(self):
        """Validate audit log entry"""
        # Ensure timestamp is set
        if not self.timestamp:
            self.timestamp = frappe.utils.now()

        # Validate severity
        if self.severity not in ["info", "warning", "error", "critical"]:
            frappe.throw("Invalid severity level")

    def before_insert(self):
        """Before insert hook"""
        # Set creation timestamp
        if not self.timestamp:
            self.timestamp = frappe.utils.now()

    def on_trash(self):
        """Prevent manual deletion of audit logs"""
        # Only allow deletion by system or during cleanup
        if frappe.session.user not in ["Administrator", "System"]:
            frappe.throw("Audit logs cannot be manually deleted")
