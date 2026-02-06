import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class MijnRoodSyncEvent(Document):
    @frappe.whitelist()
    def approve(self):
        """Approve this sync event for application."""
        if self.status != "Pending":
            frappe.throw(_("Only Pending events can be approved"))

        self.status = "Approved"
        self.reviewed_by = frappe.session.user
        self.reviewed_at = now_datetime()
        self.save()

    @frappe.whitelist()
    def reject(self):
        """Reject this sync event."""
        if self.status != "Pending":
            frappe.throw(_("Only Pending events can be rejected"))

        self.status = "Rejected"
        self.reviewed_by = frappe.session.user
        self.reviewed_at = now_datetime()
        self.save()

    @frappe.whitelist()
    def ignore_event(self):
        """Ignore this sync event (acknowledged but not applied)."""
        if self.status != "Pending":
            frappe.throw(_("Only Pending events can be ignored"))

        self.status = "Ignored"
        self.reviewed_by = frappe.session.user
        self.reviewed_at = now_datetime()
        self.save()

    @frappe.whitelist()
    def apply_event(self):
        """Apply this approved sync event to Verenigingen data."""
        if self.status != "Approved":
            frappe.throw(_("Only Approved events can be applied"))

        from verenigingen.mijnrood_sync.services.event_application_service import (
            get_event_application_service,
        )

        service = get_event_application_service()
        return service.apply_event(self.name)
