"""
Member Approval Service - Reusable approval workflow utilities.

This module provides utility functions used during the membership approval process.
The main approval orchestration lives in:
- API layer: api/membership_application_review.py::approve_membership_application()
- Service layer: services/member/approval/membership_creation_service.py::MembershipCreationService

Functions in this module:
    - resolve_membership_type(): Validate and resolve membership type with fallbacks
    - create_member_iban_history(): Initialize IBAN history tracking on approval
    - validate_approval_prerequisites(): Check member readiness for approval
"""

import logging

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.service_error_handler import handle_service_error

logger = logging.getLogger(__name__)


def resolve_membership_type(member, membership_type=None):
    """Resolve and validate membership type.

    Handles membership type resolution with fallbacks and validation.

    Args:
        member: Member document instance
        membership_type (str, optional): Explicit membership type to use

    Returns:
        str: Resolved membership type name

    Raises:
        frappe.ValidationError: If no valid membership type can be resolved
    """
    try:
        # Use provided membership type or fallback to selected
        if not membership_type:
            membership_type = getattr(member, "selected_membership_type", None)

        # Additional fallback to current membership type if selected is not set
        if not membership_type:
            membership_type = getattr(member, "current_membership_type", None)

        # If still no membership type, try to set a default from available types
        if not membership_type:
            membership_types = frappe.get_all("Membership Type", fields=["name"], limit=1)
            if membership_types:
                membership_type = membership_types[0].name
                # Set this as the selected type for the member
                try:
                    member.selected_membership_type = membership_type
                    member.save()
                    logger.info(f"Auto-assigned membership type {membership_type} to member {member.name}")
                except Exception as e:
                    logger.error(f"Could not save membership type to member: {str(e)}")
            else:
                frappe.throw(
                    _("No membership types available in the system. Please create a membership type first.")
                )

        if not membership_type:
            frappe.throw(_("Please select a membership type"))

        return membership_type

    except Exception as e:
        handle_service_error(
            e,
            "MemberApprovalService",
            "Resolve membership type",
            {"member": getattr(member, "name", "Unknown"), "membership_type": membership_type},
            raise_error=True,
        )


def create_member_iban_history(member):
    """Create initial IBAN history tracking for approved member.

    Initializes IBAN history tracking for members with banking details.

    Args:
        member: Member document instance with IBAN data

    Returns:
        OperationResult: Result with success status and created history info
    """
    try:
        if not (hasattr(member, "iban") and member.iban):
            return OperationResult.ok({"message": "No IBAN provided, skipping history creation"})

        # Check if IBAN history already exists to avoid duplicates
        existing_history = frappe.db.exists(
            "Member IBAN History", {"member": member.name, "iban": member.iban}
        )

        if existing_history:
            logger.info(f"IBAN history already exists for member {member.name}")
            return OperationResult.ok(
                {"existing_record": existing_history, "message": "IBAN history already exists"}
            )

        # Create IBAN history record using proper child table pattern
        iban_history = member.append(
            "iban_history",
            {
                "iban": member.iban,
                "bank_account_name": getattr(
                    member, "bank_account_name", member.iban.split()[-1] if member.iban else ""
                ),
                "from_date": today(),
                "is_active": 1,
                "change_reason": "Application Approval",
            },
        )

        member.save()

        return OperationResult.ok(
            {"iban_history": iban_history.name, "message": "IBAN history created successfully"}
        )

    except Exception as e:
        handle_service_error(
            e,
            "MemberApprovalService",
            "Create IBAN history",
            {"member": getattr(member, "name", "Unknown")},
            raise_error=False,
        )
        return OperationResult.from_exception(e)


def validate_approval_prerequisites(member_name):
    """Validate that member meets approval prerequisites.

    Args:
        member_name (str): Name/ID of member to validate

    Returns:
        dict: Validation result with prerequisites status
    """
    try:
        member = frappe.get_doc("Member", member_name)

        errors = []
        warnings = []

        # Check application status
        if getattr(member, "application_status", "") == "Approved":
            warnings.append("Member is already approved")

        # Check required fields
        if not getattr(member, "full_name", ""):
            errors.append("Member must have a full name")

        if not getattr(member, "email", ""):
            errors.append("Member must have an email address")

        # Check for existing active membership
        existing_membership = frappe.db.exists("Membership", {"member": member_name, "status": "Active"})
        if existing_membership:
            warnings.append(f"Member already has active membership: {existing_membership}")

        if errors:
            return OperationResult.fail(
                "Validation failed",
                errors=errors,
            )
        return OperationResult.ok(
            {
                "message": "Validation completed",
                "ready_for_approval": True,
                "warnings": warnings,
            }
        )

    except Exception as e:
        handle_service_error(
            e,
            "MemberApprovalService",
            "Validate approval prerequisites",
            {"member": member_name},
            raise_error=False,
        )
        return OperationResult.from_exception(e)
