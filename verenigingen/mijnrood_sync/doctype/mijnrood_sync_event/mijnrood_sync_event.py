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
    def approve_and_apply(self):
        """Approve and immediately apply this sync event."""
        if self.status != "Pending":
            frappe.throw(_("Only Pending events can be approved and applied"))

        self.status = "Approved"
        self.reviewed_by = frappe.session.user
        self.reviewed_at = now_datetime()
        self.save()

        from verenigingen.mijnrood_sync.services.event_application_service import (
            get_event_application_service,
        )

        service = get_event_application_service()
        return service.apply_event(self.name)

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

    @frappe.whitelist()
    def get_member_comparison_data(self):
        """Return current Frappe member field values for comparison with MijnRood data.

        Keyed by MijnRood column name so the client can directly compare
        against the new_data JSON stored on the event.

        Returns:
            dict keyed by MijnRood column name → current Frappe value
        """
        if not self.linked_member:
            return {}

        member = frappe.get_doc("Member", self.linked_member)

        from verenigingen.mijnrood_sync.field_mapping import (
            MIJNROOD_TO_MEMBER_FIELD_MAP,
            get_status_labels,
        )

        # Reverse map: Frappe field → MijnRood column(s)
        frappe_to_mijnrood = {}
        for mr_col, frappe_field in MIJNROOD_TO_MEMBER_FIELD_MAP.items():
            frappe_to_mijnrood.setdefault(frappe_field, []).append(mr_col)

        result = {}

        # Direct member fields
        for frappe_field, mr_cols in frappe_to_mijnrood.items():
            value = member.get(frappe_field) if member.get(frappe_field) else ""
            for mr_col in mr_cols:
                result[mr_col] = str(value) if value else ""

        # Membership status: Frappe stores string ("Active", "Suspended", etc.)
        # while MijnRood uses numeric IDs resolved to STATUS_ID_LABELS format.
        # Return both: raw Frappe status + display value matching the MijnRood
        # label format so the JS comparison table can show and match correctly.
        if member.get("status"):
            frappe_status = str(member.status)
            # Build reverse lookup: match Frappe status to MijnRood label
            # e.g. "Active" matches "Active (lid)", "Suspended" matches "Suspended (geschorst)"
            matched_label = frappe_status
            for _sid, label in get_status_labels().items():
                if label.lower().startswith(frappe_status.lower()):
                    matched_label = label
                    break
            result["current_membership_status_id"] = matched_label

        # Address fields from linked Address document
        if member.get("primary_address"):
            try:
                address = frappe.get_doc("Address", member.primary_address)
                result["address"] = str(address.address_line1 or "")
                result["city"] = str(address.city or "")
                result["post_code"] = str(address.pincode or "")
                result["country"] = str(address.country or "")
            except frappe.DoesNotExistError:
                pass

        # Division: look up the member's current active chapter via Chapter Member child table
        active_chapter = frappe.db.get_value(
            "Chapter Member",
            {"member": self.linked_member, "status": "Active"},
            "parent",
        )
        if active_chapter:
            result["division_id"] = str(active_chapter)

        return result
