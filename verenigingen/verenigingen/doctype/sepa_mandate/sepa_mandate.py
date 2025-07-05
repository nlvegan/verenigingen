# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today


class SEPAMandate(Document):
    def validate(self):
        self.validate_dates()
        self.validate_iban()
        self.set_status_based_on_dates()

        # Also synchronize status and is_active flag during validation
        self.sync_status_is_active()

    def sync_status_is_active(self):
        """Synchronize status and is_active flag explicitly"""
        # Make sure is_active matches status
        if self.status == "Active" and not self.is_active:
            self.is_active = 1
        elif self.status in ["Suspended", "Cancelled", "Expired"] and self.is_active:
            self.is_active = 0

    def set_status_based_on_dates(self):
        """Set expiry status based on dates"""
        # Check expiry date - this takes precedence over other statuses
        # except Cancelled which is manually set
        if self.expiry_date and getdate(self.expiry_date) < getdate(today()) and self.status != "Cancelled":
            self.status = "Expired"
            self.is_active = 0

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
        # Ensure sign date is not in the future
        if self.sign_date and getdate(self.sign_date) > getdate(today()):
            frappe.throw(_("Mandate sign date cannot be in the future"))

        # Ensure expiry date is after sign date
        if self.expiry_date and self.sign_date:
            if getdate(self.expiry_date) < getdate(self.sign_date):
                frappe.throw(_("Expiry date cannot be before sign date"))

    def validate_iban(self):
        # Comprehensive IBAN validation with mod-97
        if self.iban:
            from verenigingen.utils.iban_validator import derive_bic_from_iban, format_iban, validate_iban

            # Validate IBAN
            validation_result = validate_iban(self.iban)
            if not validation_result["valid"]:
                frappe.throw(_(validation_result["message"]))

            # Format IBAN properly
            self.iban = format_iban(self.iban)

            # Auto-derive BIC if not provided
            if not self.bic:
                derived_bic = derive_bic_from_iban(self.iban)
                if derived_bic:
                    self.bic = derived_bic
                    frappe.msgprint(_("BIC automatically derived from IBAN: {0}").format(derived_bic))

    def after_insert(self):
        """Send notification when mandate is created"""
        if self.status == "Active":
            from verenigingen.utils.sepa_notifications import SEPAMandateNotificationManager

            notification_manager = SEPAMandateNotificationManager()
            notification_manager.send_mandate_created_notification(self)

    def on_update(self):
        """
        When a mandate is updated to Active status and is used for memberships,
        check if it should be set as the current mandate
        """
        # Check for status changes
        if self.has_value_changed("status"):
            old_status = self.get_doc_before_save().status if self.get_doc_before_save() else None

            # Send notifications based on status changes
            from verenigingen.utils.sepa_notifications import SEPAMandateNotificationManager

            notification_manager = SEPAMandateNotificationManager()

            if self.status == "Active" and old_status != "Active":
                # Mandate activated
                notification_manager.send_mandate_created_notification(self)
            elif self.status == "Cancelled" and old_status != "Cancelled":
                # Mandate cancelled
                reason = self.cancellation_reason or "Cancelled by member request"
                notification_manager.send_mandate_cancelled_notification(self, reason)

        if self.member and self.status == "Active" and self.is_active and self.used_for_memberships:
            # Find if this mandate is already linked to the member
            member = frappe.get_doc("Member", self.member)

            # Check if this mandate is in the member's mandate list
            mandate_exists = False
            is_already_current = False

            for mandate_link in member.sepa_mandates:
                if mandate_link.sepa_mandate == self.name:
                    mandate_exists = True
                    if mandate_link.is_current:
                        is_already_current = True
                    break

            # If mandate isn't linked, add it
            if not mandate_exists:
                # Check if there are other active mandates
                other_active_mandates = any(
                    link.status == "Active" and link.is_current for link in member.sepa_mandates
                )

                # Add this mandate as the current one if no other active current mandates
                member.append(
                    "sepa_mandates", {"sepa_mandate": self.name, "is_current": not other_active_mandates}
                )
                member.save(ignore_permissions=True)

            # If this is the only active mandate, set it as current
            elif not is_already_current:
                other_mandates = frappe.get_all(
                    "SEPA Mandate",
                    filters={
                        "member": self.member,
                        "status": "Active",
                        "is_active": 1,
                        "name": ["!=", self.name],
                    },
                )

                if not other_mandates:
                    # Set this as the current mandate in the member's mandate list
                    for mandate_link in member.sepa_mandates:
                        if mandate_link.sepa_mandate == self.name:
                            mandate_link.is_current = 1
                        else:
                            mandate_link.is_current = 0

                    member.save(ignore_permissions=True)


def cancel_mandate(self, reason=None, cancellation_date=None):
    """
    Cancel SEPA mandate method
    """
    if not cancellation_date:
        cancellation_date = frappe.utils.today()

    # Update mandate status
    self.status = "Cancelled"
    self.is_active = 0
    self.cancelled_date = cancellation_date
    self.cancelled_reason = reason or "Mandate cancelled"

    # Add cancellation note
    cancellation_note = f"Cancelled on {cancellation_date}"
    if reason:
        cancellation_note += f" - Reason: {reason}"

    if self.notes:
        self.notes += f"\n\n{cancellation_note}"
    else:
        self.notes = cancellation_note

    # Save the mandate
    self.flags.ignore_permissions = True
    self.save()

    frappe.logger().info(f"Cancelled SEPA mandate {self.mandate_id}")


def has_permission(doc, user=None, ptype=None):
    """Custom permission check for SEPA Mandate"""
    if not user:
        user = frappe.session.user

    # Admin roles have full access
    if frappe.db.get_value(
        "Has Role",
        {
            "parent": user,
            "role": ["in", ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]],
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
            "role": ["in", ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]],
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
            return f"`tabSEPA Mandate`.member = '{member}'"

    # Default: no access
    return "1=0"
