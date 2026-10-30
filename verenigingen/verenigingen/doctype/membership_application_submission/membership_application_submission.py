# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
import frappe
from frappe import _
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
    "Unconfirmed": ("Pending Review", "Expired"),
    "Pending Review": ("Approved", "Rejected", "Superseded"),
}


class MembershipApplicationSubmission(Document):
    """A membership application: unconfirmed until the email is confirmed, then reviewed."""

    def set_status(self, status: str) -> None:
        """Move to `status` along an allowed edge only; anything else is refused."""
        if status not in ALLOWED_TRANSITIONS.get(self.status, ()):
            frappe.throw(
                _("An application cannot move from {0} to {1}.").format(self.status, status),
                frappe.ValidationError,
            )
        self.db_set("status", status)
