import frappe
from frappe import _
from frappe.utils import getdate, today

from verenigingen.utils.constants import Roles


def validate_termination_request(doc, method):
    """Validation function for termination requests"""

    # Validate that member exists and is active
    if not frappe.db.exists("Member", doc.member):
        frappe.throw(_("Member {0} does not exist").format(doc.member))

    member_status = frappe.db.get_value("Member", doc.member, "status")
    if member_status in ["Terminated", "Expired", "Banned", "Deceased"]:
        frappe.throw(_("Cannot terminate member with status: {0}").format(member_status))

    # Validate disciplinary terminations
    disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]
    if doc.termination_type in disciplinary_types:
        # Require documentation
        if not doc.disciplinary_documentation:
            frappe.throw(_("Documentation is required for disciplinary terminations"))

        # Require secondary approver for pending approval status
        if not doc.secondary_approver and doc.status == "Pending Approval":
            frappe.throw(_("Secondary approver is required for disciplinary terminations"))

        # Validate approver permissions
        if doc.secondary_approver:
            validate_approver_permissions(doc.secondary_approver)

    # Validate dates
    if doc.termination_date and getdate(doc.termination_date) < getdate(doc.request_date):
        frappe.throw(_("Termination date cannot be before request date"))

    if doc.grace_period_end and doc.termination_date:
        if getdate(doc.grace_period_end) < getdate(doc.termination_date):
            frappe.throw(_("Grace period end cannot be before termination date"))


def validate_verenigingen_settings(doc, method):
    """Validation function for Verenigingen Settings"""

    # Validate grace period settings
    if doc.default_grace_period_days:
        if doc.default_grace_period_days < 1 or doc.default_grace_period_days > 180:
            frappe.throw(_("Default grace period days must be between 1 and 180 days"))

    if doc.grace_period_notification_days:
        if doc.grace_period_notification_days < 1 or doc.grace_period_notification_days > 30:
            frappe.throw(_("Grace period notification days must be between 1 and 30 days"))

        # Ensure notification days is less than grace period days
        if (
            doc.default_grace_period_days
            and doc.grace_period_notification_days >= doc.default_grace_period_days
        ):
            frappe.throw(_("Grace period notification days must be less than default grace period days"))


def validate_membership_grace_period(doc, method):
    """Validation function for Membership grace period fields"""

    # Validate grace period expiry date
    if doc.grace_period_status == "Grace Period":
        if not doc.grace_period_expiry_date:
            frappe.throw(_("Grace period expiry date is required when grace period status is set"))

        # Ensure grace period expiry is in the future (allow same day)
        if getdate(doc.grace_period_expiry_date) < getdate(today()):
            frappe.throw(_("Grace period expiry date cannot be in the past"))

        # Optional: Validate grace period is reasonable (not too long)
        max_grace_days = (
            frappe.db.get_single_value("Verenigingen Settings", "default_grace_period_days") or 30
        )
        max_grace_days = max_grace_days * 2  # Allow up to 2x the default

        days_from_today = (getdate(doc.grace_period_expiry_date) - getdate(today())).days
        if days_from_today > max_grace_days:
            frappe.msgprint(
                _(
                    "Warning: Grace period is set for {0} days, which is longer than the recommended maximum of {1} days"
                ).format(days_from_today, max_grace_days),
                indicator="orange",
                alert=True,
            )

    elif doc.grace_period_expiry_date:
        # If grace period expiry date is set but status is not "Grace Period", clear it
        doc.grace_period_expiry_date = None
        doc.grace_period_reason = None


def validate_approver_permissions(approver_user):
    """Validate that the approver has the required permissions"""
    approver_roles = frappe.get_roles(approver_user)

    # Modernized with centralized role constants
    if not any(role in [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN] for role in approver_roles):
        # Check if national board member
        settings = frappe.get_single("Verenigingen Settings")
        if settings and settings.national_board_chapter:
            # Modernized ORM approach - find if user is national board member
            member = frappe.get_value("Member", {"user": approver_user}, "name")
            is_national_board = False

            if member:
                volunteer = frappe.get_value("Volunteer", {"member": member}, "name")
                if volunteer:
                    board_membership = frappe.db.exists(
                        "Chapter Board Member",
                        {"volunteer": volunteer, "parent": settings.national_board_chapter, "is_active": 1},
                    )
                    is_national_board = bool(board_membership)

            if not is_national_board:
                frappe.throw(
                    _("Secondary approver must be Verenigingen Administrator or National Board Member")
                )
