import frappe
from frappe.model.document import Document


class TerminationAuditEntry(Document):
    def validate(self):
        # Set timestamp if not provided
        if not self.timestamp:
            self.timestamp = frappe.utils.now()

        # Set user if not provided
        if not self.user:
            self.user = frappe.session.user
