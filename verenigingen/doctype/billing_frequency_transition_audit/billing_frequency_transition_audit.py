# Copyright (c) 2025, Veganisme Nederland and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BillingFrequencyTransitionAudit(Document):
    """Audit trail for billing frequency transitions"""

    def before_insert(self):
        """Set audit fields before insert"""
        if not self.created_by:
            self.created_by = frappe.session.user
        if not self.creation_time:
            self.creation_time = frappe.utils.now()

    def validate(self):
        """Validate audit record"""
        # Ensure member exists
        if not frappe.db.exists("Member", self.member):
            frappe.throw(f"Member {self.member} does not exist")

        # Validate frequency values
        valid_frequencies = ["Monthly", "Quarterly", "Semi-Annual", "Annual"]
        if self.old_frequency not in valid_frequencies:
            frappe.throw(f"Invalid old frequency: {self.old_frequency}")
        if self.new_frequency not in valid_frequencies:
            frappe.throw(f"Invalid new frequency: {self.new_frequency}")

        # Ensure transition is meaningful
        if self.old_frequency == self.new_frequency:
            frappe.throw("Old and new frequencies cannot be the same")

    def on_update(self):
        """Log updates to audit record"""
        if self.has_value_changed("transition_status"):
            frappe.log_info(
                {
                    "audit_record": self.name,
                    "member": self.member,
                    "status_change": f"{self.get_db_value('transition_status')} -> {self.transition_status}",
                    "updated_by": frappe.session.user,
                    "timestamp": frappe.utils.now(),
                },
                "Billing Transition Status Update",
            )
