# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.validation_utilities import DateRangeValidator, DocumentExistenceValidator
from verenigingen.verenigingen_payments.services.sepa_mandate_identity_service import (
    sepa_mandate_identity_service,
)
from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
    sepa_mandate_lifecycle_service,
)
from verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service import (
    sepa_mandate_member_integration_service,
)
from verenigingen.verenigingen_payments.services.sepa_mandate_validation_service import (
    sepa_mandate_validation_service,
)
from verenigingen.verenigingen_payments.utils.sepa_mandate_service import (
    invalidate_mandate_cache_for_member,
)


class SEPAMandate(Document):
    def validate(self):
        self.set_scheme_default()
        self.auto_generate_mandate_id()
        self.enforce_terminal_status()
        self.validate_dates()
        self.validate_iban()
        self.set_status_based_on_dates()

        # Also synchronize status and is_active flag during validation
        self.sync_status_is_active()

        # Run last: relies on the normalized IBAN (set by validate_iban) and the
        # final status (set by set_status_based_on_dates / sync_status_is_active).
        self.validate_no_duplicate_active_mandate()

    def enforce_terminal_status(self):
        """Prevent reactivating a mandate that is in a terminal state.

        Cancelled and Expired are terminal SEPA mandate states: a cancelled or
        expired mandate must not be reverted to Active/Suspended. The correct
        workflow is to create a NEW mandate. Without this guard the status field
        could be flipped back to Active on a later save, silently resurrecting a
        revoked authorization. (set_value already treats these states specially.)
        """
        if self.is_new():
            return
        previous_status = frappe.db.get_value("SEPA Mandate", self.name, "status")
        if previous_status in ("Cancelled", "Expired") and self.status != previous_status:
            # Keep the terminal status; do not allow resurrection. We restore
            # silently (rather than throw) so unrelated saves of a terminal mandate
            # still succeed, but log a warning so the rejected transition is visible.
            frappe.logger().warning(
                f"SEPA Mandate {self.name}: blocked status change "
                f"{previous_status} -> {self.status}; keeping {previous_status}."
            )
            self.status = previous_status
            self.is_active = 0

    def validate_no_duplicate_active_mandate(self):
        """Reject a second Active mandate that duplicates an existing one (same IBAN).

        A member legitimately switches banks by creating a new mandate with a
        different IBAN, which supersedes the old one via the Member SEPA Mandate
        Link `is_current` flag. But two Active mandates sharing the same IBAN are a
        genuine duplicate and must be rejected as a data-integrity error.
        """
        if self.status != "Active" or not self.member or not self.iban:
            return

        duplicate = frappe.db.exists(
            "SEPA Mandate",
            {
                "member": self.member,
                "iban": self.iban,
                "status": "Active",
                "name": ["!=", self.name or ""],
            },
        )
        if duplicate:
            frappe.throw(
                _("Member {0} already has an active SEPA mandate with this IBAN ({1}).").format(
                    self.member, self.iban
                )
            )

    def set_scheme_default(self):
        """Apply the JSON 'SEPA' default for the mandatory scheme field.

        Frappe v16 no longer applies a field's JSON default on a raw
        get_doc({...}).insert() (only at the form layer), so a mandate created
        without an explicit scheme hits a MandatoryError. Mirror the same
        controller-level default pattern used for status/mandate_id.
        """
        if not self.scheme:
            self.scheme = "SEPA"

    def auto_generate_mandate_id(self):
        """Auto-generate mandate_id using identity service"""
        # Only generate if mandate_id is not already set
        if self.mandate_id:
            return

        self.mandate_id = sepa_mandate_identity_service.generate_mandate_id(self)

    def sync_status_is_active(self):
        """Synchronize status and is_active flag using lifecycle service"""
        sepa_mandate_lifecycle_service.sync_status_and_active_flag(self)

    def set_status_based_on_dates(self):
        """Set status based on dates using lifecycle service"""
        self.status = sepa_mandate_lifecycle_service.set_status_based_on_dates(self)

    def set_value(self, fieldname, value):
        """Override set_value for special field handling"""
        # If setting is_active flag, update status accordingly
        if fieldname == "is_active":
            # Only update status if not in these special statuses
            if self.status not in ["Cancelled", "Expired", "Draft"]:
                if value:
                    # When activating, set status to Active
                    super().set_value(fieldname, value)
                    super().set_value("status", "Active")
                else:
                    # When deactivating, set status to Suspended
                    super().set_value(fieldname, value)
                    super().set_value("status", "Suspended")
            else:
                # Just set the is_active value without changing status
                super().set_value(fieldname, value)
        # If setting status, update is_active flag accordingly
        elif fieldname == "status":
            if value == "Active":
                super().set_value(fieldname, value)
                super().set_value("is_active", 1)
            elif value in ["Suspended", "Cancelled", "Expired"]:
                super().set_value(fieldname, value)
                super().set_value("is_active", 0)
            else:
                # Just set the status without changing is_active
                super().set_value(fieldname, value)
        else:
            # For other fields, just use the parent class implementation
            super().set_value(fieldname, value)
        return self

    def validate_dates(self):
        """Validate mandate dates using validation service"""
        validation_result = sepa_mandate_validation_service.validate_mandate_dates(self)

        if not validation_result["is_valid"]:
            frappe.throw("\n".join(validation_result["errors"]))

        # Show warnings if any
        for warning in validation_result["warnings"]:
            frappe.msgprint(warning, alert=True)

    def validate_iban(self):
        """Validate IBAN using validation service"""
        if not self.iban:
            return

        validation_result = sepa_mandate_validation_service.validate_mandate_iban(self)

        if not validation_result["is_valid"]:
            frappe.throw("\n".join(validation_result["errors"]))

        # Show warnings if any
        for warning in validation_result["warnings"]:
            frappe.msgprint(warning, alert=True)

    def after_insert(self):
        """Handle mandate creation using lifecycle service"""
        result = sepa_mandate_lifecycle_service.handle_mandate_creation(self)

        if not result["success"]:
            for error in result["errors"]:
                frappe.msgprint(error, alert=True)

        # Log notifications sent
        if result["notifications_sent"]:
            frappe.logger().info(f"Mandate creation notifications sent: {result['notifications_sent']}")

        # Invalidate cache for this member to ensure fresh data on next lookup
        if self.member:
            invalidate_mandate_cache_for_member(self.member)

    def on_update(self):
        """Handle mandate update using lifecycle service"""
        result = sepa_mandate_lifecycle_service.handle_mandate_update(self)

        if not result["success"]:
            for error in result["errors"]:
                frappe.msgprint(error, alert=True)

        # Log status changes and notifications
        if result["status_changed"]:
            frappe.logger().info(f"Mandate status changed for {self.name}")
        if result["notifications_sent"]:
            frappe.logger().info(f"Mandate update notifications sent: {result['notifications_sent']}")

        # Invalidate cache for this member to ensure fresh data on next lookup
        if self.member:
            invalidate_mandate_cache_for_member(self.member)

    def update_member_sepa_mandates_table(self):
        """Update the member's SEPA mandates child table using member integration service"""
        if not self.member:
            return

        result = sepa_mandate_member_integration_service.update_member_mandate_relationship(self)

        if not result["success"]:
            frappe.throw("\n".join(result["errors"]))

        # Show warnings if any
        for warning in result.get("warnings", []):
            frappe.msgprint(warning, alert=True)

    def on_trash(self):
        """Handle mandate deletion - invalidate cache"""
        # Invalidate cache for this member to ensure deleted mandate
        # doesn't appear in cached queries
        if self.member:
            invalidate_mandate_cache_for_member(self.member)


def has_permission(doc, user=None, ptype=None):
    """Custom permission check for SEPA Mandate"""
    if not user:
        user = frappe.session.user

    # Admin roles have full access
    if frappe.db.get_value(
        "Has Role",
        {
            "parent": user,
            "role": ["in", list(Roles.ADMIN_ROLES)],
        },
        "name",
    ):
        return True

    # Members can only access their own mandates
    if frappe.db.get_value("Has Role", {"parent": user, "role": "Verenigingen Member"}, "name"):
        if not doc or not doc.member:
            return False

        # Check if the mandate belongs to this member
        member = frappe.db.get_value("Member", {"email": user}, "name") or frappe.db.get_value(
            "Member", {"user": user}, "name"
        )
        return doc.member == member

    return False


def get_permission_query_conditions(user=None):
    """Custom permission query conditions for SEPA Mandate"""
    if not user:
        user = frappe.session.user

    # Admin roles can see all mandates
    if frappe.db.get_value(
        "Has Role",
        {
            "parent": user,
            "role": ["in", list(Roles.ADMIN_ROLES)],
        },
        "name",
    ):
        return ""

    # Members can only see their own mandates
    if frappe.db.get_value("Has Role", {"parent": user, "role": "Verenigingen Member"}, "name"):
        member = frappe.db.get_value("Member", {"email": user}, "name") or frappe.db.get_value(
            "Member", {"user": user}, "name"
        )
        if member:
            return f"`tabSEPA Mandate`.member = {frappe.db.escape(member)}"

    # Default: no access
    return "1=0"
