"""
Member ID Service - Centralized ID generation for members and applications.

This service provides consistent, unique ID generation for Member DocType operations.
All ID generation logic has been extracted from member.py for better maintainability.

Functions:
    - generate_member_id(): Sequential member ID generation with settings integration
    - generate_application_id(): Robust application ID with collision handling
    - validate_id_uniqueness(): Check if generated IDs are truly unique
"""

import datetime
import logging
import random
import time

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.service_error_handler import create_service_result, handle_service_error

logger = logging.getLogger(__name__)


def generate_member_id():
    """Generate a unique member ID using settings-based sequential numbering.

    Extracted from member.py without modification. Uses Verenigingen Settings
    to maintain sequential numbering with fallback to timestamp-based IDs.

    Returns:
        str: Unique member ID
    """
    if frappe.session.user == "Guest":
        return None

    try:
        settings = frappe.get_single("Verenigingen Settings")

        # Check if the field exists
        if not hasattr(settings, "last_member_id"):
            # Use a simple timestamp-based ID if settings field doesn't exist
            return str(int(time.time() * 1000))[-8:]  # Last 8 digits of timestamp

        if not settings.last_member_id:
            start_id = getattr(settings, "member_id_start", 10000)
            settings.last_member_id = start_id - 1

        new_id = int(settings.last_member_id) + 1

        settings.last_member_id = new_id
        settings.save()

        return str(new_id)
    except Exception as e:
        # Log error and fallback to simple ID generation
        handle_service_error(
            e,
            "MemberIdService",
            "Generate Member ID",
            {"fallback_used": True},
            raise_error=False,
            log_level="warning",
        )
        return str(int(time.time() * 1000))[-8:]


def generate_application_id():
    """Generate unique application ID with robust collision handling.

    Uses the robust implementation from application_helpers.py with multiple
    strategies for collision avoidance and uniqueness guarantees.

    Returns:
        str: Unique application ID in format APP-YYYYMMDD-XXXX
    """
    date_str = frappe.utils.nowdate().replace("-", "")
    max_attempts = 20  # Reduce attempts but improve strategy

    for attempt in range(max_attempts):
        # Use different strategies for better distribution
        if attempt == 0:
            # First attempt: use timestamp + microseconds for high uniqueness
            now = datetime.datetime.now()
            timestamp_part = int(now.timestamp() * 1000) % 10000  # millisecond precision
            app_id = f"APP-{date_str}-{timestamp_part:04d}"
        elif attempt < 5:
            # Early attempts: use timestamp with random offset
            timestamp_part = int(time.time() % 10000) + random.randint(-500, 500)
            timestamp_part = abs(timestamp_part) % 10000  # Keep in range
            app_id = f"APP-{date_str}-{timestamp_part:04d}"
        else:
            # Later attempts: pure random with better distribution
            random_part = random.randint(1000, 9999)
            app_id = f"APP-{date_str}-{random_part}"

        # Check for uniqueness
        if not frappe.db.exists("Member", {"application_id": app_id}):
            return app_id

    # Final fallback if all attempts failed
    import uuid

    fallback_id = f"APP-{date_str}-{str(uuid.uuid4())[:4].upper()}"
    logger.warning(f"Application ID generation required fallback: {fallback_id}")
    return fallback_id


def validate_id_uniqueness(id_value, id_type="member_id"):
    """Validate that a generated ID is truly unique in the system.

    Args:
        id_value (str): The ID to validate
        id_type (str): Type of ID - 'member_id' or 'application_id'

    Returns:
        bool: True if ID is unique, False if collision detected
    """
    if not id_value:
        return False

    field_name = id_type
    exists = frappe.db.exists("Member", {field_name: id_value})
    return not bool(exists)


def ensure_member_has_id(member_doc) -> OperationResult[str]:
    """Ensure a member document has appropriate ID assigned.

    Args:
        member_doc: Member document instance

    Returns:
        OperationResult[str]: OperationResult with member_id on success
    """
    if not member_doc.member_id and member_doc.should_have_member_id():
        member_doc.member_id = generate_member_id()
        member_doc.save()
        return OperationResult.ok(member_doc.member_id, message=_("Member ID assigned successfully"))
    return OperationResult.fail(_("Member already has an ID or doesn't qualify for one"))


def force_assign_member_id(member_doc) -> OperationResult[str]:
    """Force assign a member ID regardless of normal rules (admin only).

    Args:
        member_doc: Member document instance

    Returns:
        OperationResult[str]: OperationResult with member_id on success
    """
    # Check if user has permission
    if not frappe.has_permission("Member", "write") or "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Managers can force assign member IDs"))

    if member_doc.member_id:
        return OperationResult.fail(
            _("Member already has a member ID: {0}").format(member_doc.member_id),
            existing_id=member_doc.member_id,
        )

    member_doc.member_id = generate_member_id()
    member_doc.save()
    return OperationResult.ok(
        member_doc.member_id,
        message=_("Member ID force assigned successfully: {0}").format(member_doc.member_id),
    )
