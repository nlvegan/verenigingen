# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

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


class SEPAMandate(Document):
    def validate(self):
        self.auto_generate_mandate_id()
        self.validate_dates()
        self.validate_iban()
        self.set_status_based_on_dates()

        # Also synchronize status and is_active flag during validation
        self.sync_status_is_active()

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


def has_permission(doc, user=None, ptype=None):
    """Custom permission check for SEPA Mandate"""
    if not user:
        user = frappe.session.user

    # Admin roles have full access
    if frappe.db.get_value(
        "Has Role",
        {
            "parent": user,
            "role": ["in", ["System Manager", "Verenigingen Staff", "Verenigingen Administrator"]],
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
            "role": ["in", ["System Manager", "Verenigingen Staff", "Verenigingen Administrator"]],
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
