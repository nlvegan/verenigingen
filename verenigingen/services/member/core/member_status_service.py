"""
Member Status Service - Centralized member status management.

This service provides status management functionality that was previously
in member.py. All methods delegate to the existing member_lifecycle_service
for consistency. Extracted for better organization.

Functions:
    - set_member_application_status_defaults(): Set application status defaults
    - sync_member_status_fields(): Synchronize status fields
    - update_member_membership_status(): Update membership status based on active memberships
"""

import frappe

# Import member utils for active membership lookup
from verenigingen.utils.member_utils import get_active_membership_for_member
from verenigingen.utils.service_error_handler import handle_service_error, safe_import


def set_member_application_status_defaults(member_doc):
    """Set appropriate defaults for application_status based on member type.

    Extracted from member.py without modification. Implements logic directly
    to avoid circular import issues.

    Args:
        member_doc: Member document instance to update

    Returns:
        dict: Result with success status and any errors
    """
    try:
        # Skip application_status setting during CSV import
        # CSV imported members are backend-created, not application-created
        if getattr(member_doc, "_csv_import", False) or getattr(member_doc, "_skip_status_validation", False):
            return {
                "success": True,
                "application_status": getattr(member_doc, "application_status", None),
                "skipped": True,
            }

        # Set default application_status if not set
        if not getattr(member_doc, "application_status", ""):
            # Check if this is a new application or existing member
            if not member_doc.name or member_doc.is_new():
                member_doc.application_status = "Pending"
            else:
                # Existing member without application status - assume approved
                member_doc.application_status = "Approved"

        return {"success": True, "application_status": member_doc.application_status}

    except Exception as e:
        handle_service_error(
            e,
            "MemberStatusService",
            "Set application status defaults",
            {"member": getattr(member_doc, "name", "Unknown")},
            raise_error=False,
        )
        return {"success": False, "errors": [str(e)]}


def sync_member_status_fields(member_doc):
    """Ensure status and application_status fields are synchronized.

    Extracted from member.py without modification. Implements logic directly
    to avoid circular import issues.

    Args:
        member_doc: Member document instance to synchronize

    Returns:
        dict: Result with success status and any errors
    """
    try:
        # Ensure application_status is set
        set_member_application_status_defaults(member_doc)

        # Update membership status based on current memberships
        update_member_membership_status(member_doc)

        return {
            "success": True,
            "status": member_doc.status,
            "application_status": member_doc.application_status,
            "membership_status": member_doc.membership_status,
        }

    except Exception as e:
        handle_service_error(
            e,
            "MemberStatusService",
            "Sync status fields",
            {"member": getattr(member_doc, "name", "Unknown")},
            raise_error=False,
        )
        return {"success": False, "errors": [str(e)]}


def update_member_membership_status(member_doc):
    """Update member's membership_status field based on active memberships.

    Extracted from member.py without modification. Implements the logic directly
    to avoid circular import issues with member_lifecycle_service.

    Args:
        member_doc: Member document instance to update

    Returns:
        str or None: Updated membership status or None if error occurred
    """
    try:
        from frappe.utils import getdate, today

        # Check for any submitted membership (active or expired)
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member_doc.name, "docstatus": 1},  # Submitted memberships
            fields=["name", "membership_type", "status", "renewal_date", "start_date"],
            order_by="renewal_date desc",
            limit=1,
        )

        if memberships:
            membership = memberships[0]
            # Check if membership is actually active or expired
            renewal_date = getdate(membership.get("renewal_date", today()))
            if renewal_date >= getdate(today()):
                membership_status = "Active"
            else:
                membership_status = "Expired"
        else:
            # No submitted membership found
            membership_status = "Lapsed"

        # Update the member document (but don't save - let caller handle save)
        member_doc.membership_status = membership_status

        return membership_status

    except Exception as e:
        handle_service_error(
            e,
            "MemberStatusService",
            "Update membership status",
            {"member": getattr(member_doc, "name", "Unknown")},
            raise_error=False,
        )
        return None


def get_member_status_color(status):
    """Get Bootstrap color class for member status display.

    Args:
        status (str): Member status to get color for

    Returns:
        str: Bootstrap color class
    """
    # Simple status color mapping without lifecycle service dependency
    status_colors = {
        "Active": "success",
        "Expired": "warning",
        "Lapsed": "secondary",
        "Pending": "info",
        "Suspended": "warning",
        "Terminated": "danger",
        "Rejected": "danger",
    }
    return status_colors.get(status, "secondary")


def validate_status_transition(member_doc, new_status):
    """Validate that a status transition is allowed.

    Args:
        member_doc: Member document instance
        new_status (str): New status to transition to

    Returns:
        dict: Validation result with valid/message fields
    """
    current_status = getattr(member_doc, "status", "")

    # Define allowed transitions
    allowed_transitions = {
        "": ["Active", "Pending"],
        "Pending": ["Active", "Rejected", "Suspended"],
        "Active": ["Suspended", "Terminated"],
        "Suspended": ["Active", "Terminated"],
        "Terminated": [],  # Terminal state
        "Rejected": [],  # Terminal state
    }

    if current_status in allowed_transitions:
        if new_status in allowed_transitions[current_status]:
            return {"valid": True}
        else:
            return {"valid": False, "message": f"Cannot transition from '{current_status}' to '{new_status}'"}
    else:
        return {"valid": False, "message": f"Unknown current status: '{current_status}'"}


def get_member_status_summary(member_doc):
    """Get a summary of member's current status information.

    Args:
        member_doc: Member document instance

    Returns:
        dict: Status summary with all relevant status fields
    """
    return {
        "member_name": member_doc.name,
        "full_name": getattr(member_doc, "full_name", ""),
        "status": getattr(member_doc, "status", ""),
        "application_status": getattr(member_doc, "application_status", ""),
        "membership_status": getattr(member_doc, "membership_status", ""),
        "is_application": bool(getattr(member_doc, "application_status", "")),
        "status_color": get_member_status_color(getattr(member_doc, "status", "")),
    }
