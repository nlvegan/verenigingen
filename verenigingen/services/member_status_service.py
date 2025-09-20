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

from verenigingen.utils.service_error_handler import handle_service_error, safe_import

# Safe import of lifecycle service with fallback
try:
    from verenigingen.services.member_lifecycle_service import member_lifecycle_service
except ImportError as e:
    handle_service_error(
        e,
        "MemberStatusService",
        "Import member lifecycle service",
        {"fallback_used": True},
        raise_error=False,
        log_level="warning",
    )

    # Create minimal fallback service
    class FallbackLifecycleService:
        def set_application_status_defaults(self, member_doc):
            return {"success": False, "errors": ["Lifecycle service not available"]}

        def sync_status_fields(self, member_doc):
            return {"success": False, "errors": ["Lifecycle service not available"]}

        def update_membership_status(self, member_doc):
            return {"success": False, "errors": ["Lifecycle service not available"]}

        def get_status_color(self, status):
            return "secondary"  # Default Bootstrap color

        def is_application_member(self, member_doc):
            return bool(getattr(member_doc, "application_status", ""))

    member_lifecycle_service = FallbackLifecycleService()


def set_member_application_status_defaults(member_doc):
    """Set appropriate defaults for application_status based on member type.

    Extracted from member.py without modification. Delegates to the existing
    member_lifecycle_service for consistent status management.

    Args:
        member_doc: Member document instance to update

    Returns:
        dict: Result with success status and any errors
    """
    # Use lifecycle service for setting application status defaults
    result = member_lifecycle_service.set_application_status_defaults(member_doc)

    if not result["success"]:
        frappe.log_error(
            f"Error setting application status defaults for {member_doc.name}: {result['errors']}"
        )

    return result


def sync_member_status_fields(member_doc):
    """Ensure status and application_status fields are synchronized.

    Extracted from member.py without modification. Delegates to the existing
    member_lifecycle_service for consistent status synchronization.

    Args:
        member_doc: Member document instance to synchronize

    Returns:
        dict: Result with success status and any errors
    """
    # Use lifecycle service for status synchronization
    result = member_lifecycle_service.sync_status_fields(member_doc)

    if not result["success"]:
        frappe.log_error(f"Error syncing status fields for {member_doc.name}: {result['errors']}")

    return result


def update_member_membership_status(member_doc):
    """Update member's membership_status field based on active memberships.

    Extracted from member.py without modification. Delegates to the existing
    member_lifecycle_service for consistent membership status updates.

    Args:
        member_doc: Member document instance to update

    Returns:
        str or None: Updated membership status or None if error occurred
    """
    # Use lifecycle service for membership status updates
    result = member_lifecycle_service.update_membership_status(member_doc)

    if not result["success"]:
        frappe.log_error(f"Error updating membership status for {member_doc.name}: {result['errors']}")
        return None

    return result["membership_status"]


def get_member_status_color(status):
    """Get Bootstrap color class for member status display.

    Args:
        status (str): Member status to get color for

    Returns:
        str: Bootstrap color class
    """
    return member_lifecycle_service.get_status_color(status)


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
        "is_application": member_lifecycle_service.is_application_member(member_doc),
        "status_color": get_member_status_color(getattr(member_doc, "status", "")),
    }
