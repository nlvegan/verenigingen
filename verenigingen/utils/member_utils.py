"""
Member utility functions for consistent member operations across the Verenigingen app.

This module provides standardized utilities for common member-related operations,
eliminating code duplication and ensuring consistent behavior.
"""

import functools
from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository


def _validate_member_fields(fields: List[str]) -> List[str]:
    """
    Validate that fields exist in the Member DocType.

    Args:
        fields: List of field names to validate

    Returns:
        List of validated field names that actually exist

    Raises:
        Warning logged for non-existent fields
    """
    try:
        # Get Member DocType meta
        member_meta = frappe.get_meta("Member")
        valid_fields = []

        # Standard fields that always exist on every DocType
        standard_fields = ["name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"]

        for field in fields:
            if field in standard_fields or member_meta.has_field(field):
                valid_fields.append(field)
            else:
                frappe.logger().warning(f"Field '{field}' is not present in Member DocType - skipping")

        return valid_fields
    except Exception as e:
        frappe.logger().error(f"Error validating Member fields: {str(e)}")
        # Return the original fields as fallback, let Frappe handle the error
        return fields


def get_member_name_for_user(user_email: str) -> Optional[str]:
    """
    Get member name/ID for a specific user with standardized lookup pattern.

    Args:
        user_email: Email address of the user (or username)

    Returns:
        Member name/ID if found, None otherwise

    Note:
        This function tries two lookup strategies:
        1. By user field (primary - explicit User link)
        2. By email field (fallback for legacy records)

    Error Handling:
        Returns None if no member found - caller should handle explicitly.
    """
    if not user_email:
        frappe.logger().warning("get_member_name_for_user called with empty user_email")
        return None

    try:
        # Primary lookup: by user field (explicit User link)
        member_name = frappe.db.get_value("Member", {"user": user_email})

        if not member_name:
            # Fallback lookup: by email field (for legacy records)
            member_name = frappe.db.get_value("Member", {"email": user_email})

        return member_name
    except Exception as e:
        frappe.logger().error(f"Error looking up member for user {user_email}: {str(e)}")
        return None


def get_current_user_member_name() -> Optional[str]:
    """
    Get member name/ID for the current user with standardized lookup pattern.

    Returns:
        Member name/ID if found, None otherwise

    Note:
        This function tries two lookup strategies:
        1. By user field (primary - explicit User link)
        2. By email field (fallback for legacy records)

    Error Handling:
        Returns None if no member found - caller should handle explicitly.
        Use get_current_user_member_doc() for automatic exception throwing.
    """
    return get_member_name_for_user(frappe.session.user)


def get_current_user_member_doc():
    """
    Get the complete Member document for the current user.

    Returns:
        Member document if found

    Raises:
        frappe.DoesNotExistError: If no member record found

    Error Handling:
        Automatically throws exception if no member found.
        Use get_current_user_member_name() for None return pattern.
    """
    member_name = get_current_user_member_name()

    if not member_name:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    try:
        return frappe.get_doc("Member", member_name)
    except frappe.DoesNotExistError:
        frappe.throw(_("Member record exists but cannot be accessed"), frappe.PermissionError)
    except Exception as e:
        frappe.logger().error(f"Error fetching member document {member_name}: {str(e)}")
        frappe.throw(_("Error accessing member record"), frappe.ValidationError)


def get_current_user_member_name_required() -> str:
    """
    Get member name/ID for current user, throwing exception if not found.

    Returns:
        Member name/ID (guaranteed to exist)

    Raises:
        frappe.DoesNotExistError: If no member record found

    Use Case:
        When you need member name/ID and want automatic error handling
        without fetching the full document.
    """
    member_name = get_current_user_member_name()

    if not member_name:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    return member_name


def get_current_user_member_info() -> Optional[Dict[str, Any]]:
    """
    Get basic member information for the current user with field validation.

    Returns:
        Dictionary with member info if found, None otherwise

    Fields returned (if they exist in Member DocType):
        - name: Member document name/ID
        - full_name: Member's full name
        - email: Member's email
        - status: Current membership status (note: not member_status)
        - payment_method: Payment method preference
        - mollie_customer_id: Mollie customer ID (if applicable)
        - mollie_subscription_id: Mollie subscription ID (if applicable)
        - subscription_status: Mollie subscription status (if applicable)
    """
    member_name = get_current_user_member_name()

    if not member_name:
        return None

    # Define desired fields and validate against DocType schema
    desired_fields = [
        "name",
        "full_name",
        "email",
        "status",  # Corrected from "member_status"
        "payment_method",
        "mollie_customer_id",
        "mollie_subscription_id",
        "subscription_status",
    ]

    # Validate fields exist in Member DocType
    valid_fields = _validate_member_fields(desired_fields)

    try:
        member_info = frappe.db.get_value("Member", member_name, valid_fields, as_dict=True)
        return member_info
    except Exception as e:
        frappe.logger().error(f"Error fetching member info for {member_name}: {str(e)}")
        return None


def require_member_record(error_message: Optional[str] = None) -> Callable:
    """
    Decorator to require a valid member record for the current user.

    Args:
        error_message: Custom error message if member not found

    Returns:
        Decorated function

    Raises:
        frappe.DoesNotExistError: If no member record found

    Usage:
        @require_member_record("Must be a member to access this feature")
        @frappe.whitelist()
        def my_member_only_function():
            # This function requires a valid member record
            pass
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            member_name = get_current_user_member_name()
            if not member_name:
                message = error_message or _("You must be a registered member to access this feature")
                frappe.throw(message, frappe.DoesNotExistError)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def has_mollie_subscription() -> bool:
    """
    Check if current user has an active Mollie subscription.

    Returns:
        True if user has Mollie customer ID and active subscription

    Note:
        Uses field validation to ensure compatibility with Member DocType schema.
    """
    member_info = get_current_user_member_info()

    if not member_info:
        return False

    # Check all required fields exist before using them
    has_payment_method = "payment_method" in member_info and member_info.get("payment_method") == "Mollie"
    has_customer_id = "mollie_customer_id" in member_info and bool(member_info.get("mollie_customer_id"))
    has_subscription_id = "mollie_subscription_id" in member_info and bool(
        member_info.get("mollie_subscription_id")
    )
    has_active_status = (
        "subscription_status" in member_info and member_info.get("subscription_status") == "active"
    )

    return has_payment_method and has_customer_id and has_subscription_id and has_active_status


def validate_member_ownership(member_id: str, error_message: str = None) -> None:
    """
    Validate that the current user owns the specified member record with improved security.

    Args:
        member_id: Member document name/ID to validate
        error_message: Custom error message for ownership violation

    Raises:
        frappe.DoesNotExistError: If current user has no member record
        frappe.PermissionError: If user doesn't own the member record
        frappe.ValidationError: If member_id is invalid

    Security Notes:
        - Validates both users have valid member records
        - Prevents access to non-existent member IDs
        - Logs security violations for audit purposes
    """
    # Validate inputs
    if not member_id or not isinstance(member_id, str):
        frappe.throw(_("Invalid member ID provided"), frappe.ValidationError)

    # Get current user's member record
    current_member = get_current_user_member_name()
    if not current_member:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    # Validate target member exists
    if not frappe.db.exists("Member", member_id):
        frappe.logger().warning(
            f"Security: User {frappe.session.user} attempted to access non-existent member {member_id}"
        )
        frappe.throw(_("The requested member record does not exist"), frappe.DoesNotExistError)

    # Validate ownership
    if current_member != member_id:
        # Log potential security violation
        frappe.logger().warning(
            f"Security: User {frappe.session.user} (member: {current_member}) attempted to access member {member_id}"
        )

        message = error_message or _("You can only access your own member information")
        frappe.throw(message, frappe.PermissionError)


def get_volunteer_for_member(member_name: str) -> Optional[str]:
    """
    Get volunteer record name for a given member with standardized lookup pattern.

    Args:
        member_name: Member document name/ID

    Returns:
        Volunteer record name if found, None otherwise

    Error Handling:
        Returns None if no volunteer found or on error.
        Logs errors for debugging.
    """
    if not member_name:
        frappe.logger().warning("get_volunteer_for_member called with empty member_name")
        return None

    try:
        volunteer_name = frappe.db.get_value("Volunteer", {"member": member_name}, "name")
        return volunteer_name
    except Exception as e:
        frappe.logger().error(f"Error looking up volunteer for member {member_name}: {str(e)}")
        return None


def get_volunteer_for_current_user() -> Optional[str]:
    """
    Get volunteer record name for the current user.

    Returns:
        Volunteer record name if found, None otherwise

    Note:
        Combines member lookup with volunteer lookup for convenience.
    """
    member_name = get_current_user_member_name()
    if not member_name:
        return None

    return get_volunteer_for_member(member_name)


def get_active_membership_for_member(
    member_name: str, fields: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Get active membership record for a given member with field validation.

    Args:
        member_name: Member document name/ID
        fields: List of fields to retrieve (defaults to ["name", "status", "membership_type"])

    Returns:
        Dictionary with membership info if found, None otherwise

    Error Handling:
        Returns None if no active membership found or on error.
        Validates fields against Membership DocType schema.
    """
    if not member_name:
        frappe.logger().warning("get_active_membership_for_member called with empty member_name")
        return None

    # Default fields to retrieve
    if fields is None:
        fields = ["name", "status", "membership_type"]

    # Validate fields exist in Membership DocType
    try:
        membership_meta = frappe.get_meta("Membership")
        valid_fields = []

        # Standard fields that always exist on every DocType
        standard_fields = ["name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"]

        for field in fields:
            if field in standard_fields or membership_meta.has_field(field):
                valid_fields.append(field)
            else:
                frappe.logger().warning(f"Field '{field}' is not present in Membership DocType - skipping")

        if not valid_fields:
            frappe.logger().warning("No valid fields specified for membership lookup")
            return None

    except Exception as e:
        frappe.logger().error(f"Error validating Membership fields: {str(e)}")
        # Use original fields as fallback
        valid_fields = fields

    try:
        membership_info = frappe.db.get_value(
            "Membership",
            {"member": member_name, "status": "Active", "docstatus": 1},
            valid_fields,
            as_dict=True,
        )
        return membership_info
    except Exception as e:
        frappe.logger().error(f"Error looking up active membership for member {member_name}: {str(e)}")
        return None


def get_active_membership_for_current_user(fields: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """
    Get active membership record for the current user.

    Args:
        fields: List of fields to retrieve

    Returns:
        Dictionary with membership info if found, None otherwise

    Note:
        Combines member lookup with active membership lookup for convenience.
    """
    member_name = get_current_user_member_name()
    if not member_name:
        return None

    return get_active_membership_for_member(member_name, fields)


def get_member_chapters(member_name: str, active_only: bool = True) -> List[str]:
    """
    Get list of chapters a member belongs to with standardized lookup pattern.

    Args:
        member_name: Member document name/ID
        active_only: Whether to only return active chapter memberships (default: True)

    Returns:
        List of chapter names the member belongs to

    Error Handling:
        Returns empty list if no chapters found or on error.
        Logs errors for debugging.

    Note:
        Chapter Member DocType has member field and parent field (chapter name).
        Status field indicates if the chapter membership is active.
    """
    if not member_name:
        frappe.logger().warning("get_member_chapters called with empty member_name")
        return []

    try:
        # Build filters
        filters = {"member": member_name}
        if active_only:
            filters["status"] = "Active"

        # Get chapter names (stored in parent field)
        chapter_names = frappe.db.get_all(
            "Chapter Member", filters=filters, pluck="parent"  # parent field contains the chapter name
        )

        return chapter_names or []

    except Exception as e:
        frappe.logger().error(f"Error looking up chapters for member {member_name}: {str(e)}")
        return []


def get_current_user_chapters(active_only: bool = True) -> List[str]:
    """
    Get list of chapters the current user belongs to.

    Args:
        active_only: Whether to only return active chapter memberships

    Returns:
        List of chapter names the current user belongs to

    Note:
        Combines member lookup with chapter lookup for convenience.
    """
    member_name = get_current_user_member_name()
    if not member_name:
        return []

    return get_member_chapters(member_name, active_only)


def is_member_volunteer(member_name: str) -> bool:
    """
    Check if a member has an associated volunteer record.

    Args:
        member_name: Member document name/ID

    Returns:
        True if member has volunteer record, False otherwise
    """
    return bool(get_volunteer_for_member(member_name))


def is_current_user_volunteer() -> bool:
    """
    Check if the current user has an associated volunteer record.

    Returns:
        True if current user has volunteer record, False otherwise
    """
    return bool(get_volunteer_for_current_user())


def get_member_customer(member_name: str) -> Optional[str]:
    """
    Get the customer linked to a member.

    Args:
        member_name: Member document name/ID

    Returns:
        Customer name if found, None otherwise

    Note:
        Members are typically linked to Customer records for billing purposes.
    """
    if not member_name:
        frappe.logger().warning("get_member_customer called with empty member_name")
        return None

    try:
        customer = frappe.db.get_value("Member", member_name, "customer")
        return customer
    except Exception as e:
        frappe.logger().error(f"Error looking up customer for member {member_name}: {str(e)}")
        return None


def get_member_for_customer(customer_name: str) -> Optional[str]:
    """
    Get the member linked to a customer (reverse lookup).

    Args:
        customer_name: Customer document name/ID

    Returns:
        Member name if found, None otherwise

    Note:
        This is useful when processing payments or invoices.
    """
    if not customer_name:
        frappe.logger().warning("get_member_for_customer called with empty customer_name")
        return None

    try:
        member = frappe.db.get_value("Member", {"customer": customer_name}, "name")
        return member
    except Exception as e:
        frappe.logger().error(f"Error looking up member for customer {customer_name}: {str(e)}")
        return None


def get_member_sepa_mandate(member_name: str, active_only: bool = True) -> Optional[Dict[str, Any]]:
    """
    Get SEPA mandate for a member.

    Args:
        member_name: Member document name/ID
        active_only: Whether to only return active mandates (default: True)

    Returns:
        Dictionary with mandate info if found, None otherwise

    Fields returned:
        - name: Mandate document name/ID
        - mandate_id: SEPA mandate identifier
        - status: Mandate status
        - iban: Bank account IBAN
        - sign_date: Date mandate was signed
    """
    if not member_name:
        frappe.logger().warning("get_member_sepa_mandate called with empty member_name")
        return None

    try:
        filters = {"member": member_name}
        if active_only:
            filters["status"] = "Active"

        mandate_info = frappe.db.get_value(
            "SEPA Mandate", filters, ["name", "mandate_id", "status", "iban", "sign_date"], as_dict=True
        )
        return mandate_info
    except Exception as e:
        frappe.logger().error(f"Error looking up SEPA mandate for member {member_name}: {str(e)}")
        return None


def has_active_sepa_mandate(member_name: str) -> bool:
    """
    Check if a member has an active SEPA mandate.

    Args:
        member_name: Member document name/ID

    Returns:
        True if member has active SEPA mandate, False otherwise
    """
    return bool(get_member_sepa_mandate(member_name, active_only=True))


def get_volunteer_name_for_user(user_email: str) -> Optional[str]:
    """
    Get volunteer record name for a specific user with standardized lookup pattern.

    Args:
        user_email: Email address of the user

    Returns:
        Volunteer record name if found, None otherwise

    Note:
        This function tries two lookup strategies:
        1. By email field (primary)
        2. By user field (fallback for older records)

    Error Handling:
        Returns None if no volunteer found - caller should handle explicitly.
        Logs errors for debugging purposes.
    """
    if not user_email:
        frappe.logger().warning("get_volunteer_name_for_user called with empty user_email")
        return None

    try:
        # Primary lookup: by email field
        volunteer_name = frappe.db.get_value("Volunteer", {"email": user_email}, "name")

        if not volunteer_name:
            # Fallback lookup: by user field (for compatibility)
            volunteer_name = frappe.db.get_value("Volunteer", {"user": user_email}, "name")

        return volunteer_name
    except Exception as e:
        frappe.logger().error(f"Error looking up volunteer for user {user_email}: {str(e)}")
        return None


# ============================================================================
# DUES SCHEDULE UTILITIES
# ============================================================================
# Extracted from dues_schedule_health_manager.py and other scattered queries
# to provide centralized, reusable dues schedule lookup functions


def _validate_dues_schedule_fields(fields: List[str]) -> List[str]:
    """
    Validate that fields exist in the Membership Dues Schedule DocType.

    Args:
        fields: List of field names to validate

    Returns:
        List of validated field names that actually exist

    Note:
        Internal helper function for dues schedule field validation.
        Logs warnings for non-existent fields but continues with valid ones.
    """
    try:
        # Get Membership Dues Schedule DocType meta
        schedule_meta = frappe.get_meta("Membership Dues Schedule")
        valid_fields = []

        # Standard fields that always exist on every DocType
        standard_fields = ["name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"]

        for field in fields:
            if field in standard_fields or schedule_meta.has_field(field):
                valid_fields.append(field)
            else:
                frappe.logger().warning(
                    f"Field '{field}' is not present in Membership Dues Schedule DocType - skipping"
                )

        return valid_fields
    except Exception as e:
        frappe.logger().error(f"Error validating Membership Dues Schedule fields: {str(e)}")
        # Return the original fields as fallback, let Frappe handle the error
        return fields


def get_member_dues_schedule(
    member_name: str,
    status_filter: Optional[str] = "Active",
    fields: Optional[List[str]] = None,
    include_template: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Get dues schedule information for a member with comprehensive field validation.

    This function now uses DuesScheduleRepository for consistent data access.
    Maintains backward compatibility by returning dict instead of ScheduleInfo dataclass.

    Args:
        member_name: Member document name/ID
        status_filter: Schedule status to filter by (default: "Active")
                      Common values: "Active", "Paused", "Cancelled"
                      Use None to skip status filtering
        fields: List of fields to retrieve. Defaults to common fields:
               ["name", "dues_rate", "billing_frequency", "next_invoice_date",
                "status", "membership", "membership_type"]
        include_template: Whether to include template schedules (default: False)
                         Templates are excluded by default (is_template=0)

    Returns:
        Dictionary with schedule info if found, None otherwise

    Error Handling:
        - Returns None if member_name is empty (logs warning)
        - Returns None if no schedule found (no error logged - this is normal)
        - Returns None on database errors (logs error with context)
        - Validates fields against DocType schema before query

    Examples:
        >>> # Get basic active schedule info
        >>> schedule = get_member_dues_schedule("MEM-001")
        >>> if schedule:
        ...     print(f"Dues rate: {schedule.dues_rate}")

        >>> # Get schedule with custom fields
        >>> schedule = get_member_dues_schedule(
        ...     "MEM-001",
        ...     fields=["name", "custom_amount_reason", "custom_amount_approved_by"]
        ... )

        >>> # Get paused schedules
        >>> schedule = get_member_dues_schedule("MEM-001", status_filter="Paused")

        >>> # Get any schedule regardless of status
        >>> schedule = get_member_dues_schedule("MEM-001", status_filter=None)
    """
    if not member_name:
        frappe.logger().warning("get_member_dues_schedule called with empty member_name")
        return None

    # Default fields to retrieve (commonly used across codebase)
    if fields is None:
        fields = [
            "name",
            "dues_rate",
            "billing_frequency",
            "next_invoice_date",
            "status",
            "membership",
            "membership_type",
        ]

    # Validate fields exist in Membership Dues Schedule DocType
    valid_fields = _validate_dues_schedule_fields(fields)

    if not valid_fields:
        frappe.logger().warning("No valid fields specified for dues schedule lookup")
        return None

    try:
        # Use repository for consistent data access
        repo = DuesScheduleRepository()

        # Handle status filtering
        if status_filter == "Active":
            schedule_info = repo.get_active_schedule(member_name, fields=valid_fields)
        else:
            # For other status values or None, use direct query
            # Repository doesn't have methods for Paused/Cancelled/None status yet
            filters = {"member": member_name}
            if not include_template:
                filters["is_template"] = 0
            if status_filter is not None:
                filters["status"] = status_filter

            schedule_result = frappe.db.get_value(
                "Membership Dues Schedule", filters, valid_fields, as_dict=True
            )
            return schedule_result

        # Convert ScheduleInfo dataclass to dict for backward compatibility
        if schedule_info:
            return {field: getattr(schedule_info, field, None) for field in valid_fields}

        return None

    except Exception as e:
        # Log error with context for debugging
        frappe.logger().error(
            f"Error looking up dues schedule for member {member_name} "
            f"(status_filter={status_filter}, include_template={include_template}): {str(e)}"
        )
        return None


def get_member_dues_schedule_name(
    member_name: str,
    status_filter: Optional[str] = "Active",
    include_template: bool = False,
) -> Optional[str]:
    """
    Get dues schedule name/ID for a member (simplified version).

    Convenience function when you only need the schedule name, not full details.
    This is more efficient than fetching full schedule data.

    Args:
        member_name: Member document name/ID
        status_filter: Schedule status to filter by (default: "Active")
                      Use None to skip status filtering
        include_template: Whether to include template schedules (default: False)

    Returns:
        Schedule name/ID if found, None otherwise

    Error Handling:
        Returns None if no schedule found or on error.
        Logs appropriate warning/error messages.

    Examples:
        >>> # Get active schedule name
        >>> schedule_name = get_member_dues_schedule_name("MEM-001")
        >>> if schedule_name:
        ...     print(f"Found schedule: {schedule_name}")

        >>> # Check if member has any schedule (regardless of status)
        >>> schedule_name = get_member_dues_schedule_name("MEM-001", status_filter=None)
    """
    if not member_name:
        frappe.logger().warning("get_member_dues_schedule_name called with empty member_name")
        return None

    try:
        # Use repository for consistent query pattern - just get the name field
        schedule_info = get_member_dues_schedule(
            member_name=member_name,
            status_filter=status_filter,
            fields=["name"],
            include_template=include_template,
        )

        # Extract name from result
        schedule_name = schedule_info.get("name") if schedule_info else None

        return schedule_name

    except Exception as e:
        frappe.logger().error(
            f"Error looking up dues schedule name for member {member_name} "
            f"(status_filter={status_filter}): {str(e)}"
        )
        return None


def get_member_active_or_paused_schedule(
    member_name: str,
    fields: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get active OR paused dues schedule for a member.

    This function now uses DuesScheduleRepository for consistent data access.
    Maintains backward compatibility by returning dict instead of ScheduleInfo dataclass.

    Args:
        member_name: Member document name/ID
        fields: List of fields to retrieve (optional)

    Returns:
        Dictionary with schedule info if found (either Active or Paused), None otherwise

    Error Handling:
        Returns None if no active or paused schedule found.
        Logs errors for database issues.

    Examples:
        >>> # Find active or paused schedule (useful for amendments)
        >>> schedule = get_member_active_or_paused_schedule("MEM-001")
        >>> if schedule:
        ...     print(f"Found {schedule.status} schedule: {schedule.name}")

    Note:
        Uses DuesScheduleRepository.get_active_or_paused_schedule() for consistent behavior.
    """
    if not member_name:
        frappe.logger().warning("get_member_active_or_paused_schedule called with empty member_name")
        return None

    # Default fields if not specified
    if fields is None:
        fields = ["name", "dues_rate", "billing_frequency", "status", "next_invoice_date"]

    # Validate fields
    valid_fields = _validate_dues_schedule_fields(fields)

    if not valid_fields:
        frappe.logger().warning("No valid fields specified for active/paused schedule lookup")
        return None

    try:
        # Use repository for consistent data access
        repo = DuesScheduleRepository()
        schedule_info = repo.get_active_or_paused_schedule(member_name, fields=valid_fields)

        # Convert ScheduleInfo dataclass to dict for backward compatibility
        if schedule_info:
            return {field: getattr(schedule_info, field, None) for field in valid_fields}

        return None

    except Exception as e:
        frappe.logger().error(
            f"Error looking up active/paused dues schedule for member {member_name}: {str(e)}"
        )
        return None


def get_member_active_or_paused_schedule_name(member_name: str) -> Optional[str]:
    """
    Get name of active OR paused dues schedule for a member (simplified version).

    Convenience function when you only need the schedule name.
    Commonly used in amendment and cancellation workflows.

    Args:
        member_name: Member document name/ID

    Returns:
        Schedule name/ID if found (either Active or Paused), None otherwise

    Examples:
        >>> schedule_name = get_member_active_or_paused_schedule_name("MEM-001")
        >>> if schedule_name:
        ...     # Can now cancel or amend this schedule
        ...     pass
    """
    if not member_name:
        frappe.logger().warning("get_member_active_or_paused_schedule_name called with empty member_name")
        return None

    try:
        # Use helper function - just get the name field
        schedule_info = get_member_active_or_paused_schedule(member_name, fields=["name"])
        return schedule_info.get("name") if schedule_info else None

    except Exception as e:
        frappe.logger().error(
            f"Error looking up active/paused dues schedule name for member {member_name}: {str(e)}"
        )
        return None


def has_active_dues_schedule(member_name: str) -> bool:
    """
    Check if a member has an active dues schedule.

    Convenience function for boolean checks. More readable than checking
    if get_member_dues_schedule_name() returns a value.

    Args:
        member_name: Member document name/ID

    Returns:
        True if member has active dues schedule, False otherwise

    Examples:
        >>> if has_active_dues_schedule("MEM-001"):
        ...     print("Member has active billing")
        >>> else:
        ...     print("No active billing schedule")
    """
    if not member_name:
        return False

    try:
        # Direct exists check for Active schedule
        return bool(
            frappe.db.exists(
                "Membership Dues Schedule", {"member": member_name, "status": "Active", "is_template": 0}
            )
        )
    except Exception as e:
        frappe.logger().error(
            f"Error checking active dues schedule existence for member {member_name}: {str(e)}"
        )
        return False


def has_any_dues_schedule(member_name: str) -> bool:
    """
    Check if a member has ANY dues schedule (regardless of status).

    Useful for checking if a member has ever had billing set up.

    Args:
        member_name: Member document name/ID

    Returns:
        True if member has any dues schedule, False otherwise

    Examples:
        >>> if has_any_dues_schedule("MEM-001"):
        ...     print("Member has billing history")
    """
    if not member_name:
        return False

    try:
        # Use helper function with no status filter to check for ANY schedule
        schedule_name = get_member_dues_schedule_name(member_name, status_filter=None)
        return bool(schedule_name)
    except Exception as e:
        frappe.logger().error(f"Error checking dues schedule existence for member {member_name}: {str(e)}")
        return False


def get_dues_schedule_for_membership(
    membership_name: str,
    fields: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get dues schedule for a specific membership record.

    Extracted from membership/dues_schedule_manager.py (line 350).
    This is useful when working with membership records and needing their
    associated dues schedule.

    Args:
        membership_name: Membership document name/ID
        fields: List of fields to retrieve (optional)

    Returns:
        Dictionary with schedule info if found, None otherwise

    Error Handling:
        Returns None if no schedule found or on error.
        Logs appropriate messages for debugging.

    Examples:
        >>> # Get dues schedule for a specific membership
        >>> membership = frappe.get_doc("Membership", "MEMB-2025-00123")
        >>> schedule = get_dues_schedule_for_membership(membership.name)
        >>> if schedule:
        ...     print(f"Billing: {schedule.dues_rate} per {schedule.billing_frequency}")

    Note:
        Memberships may not always have dues schedules, especially:
        - Draft/unsubmitted memberships
        - Cancelled memberships
        - Legacy records before dues schedule system
    """
    if not membership_name:
        frappe.logger().warning("get_dues_schedule_for_membership called with empty membership_name")
        return None

    # Default fields
    if fields is None:
        fields = ["name", "dues_rate", "billing_frequency", "status", "member"]

    # Validate fields
    valid_fields = _validate_dues_schedule_fields(fields)

    if not valid_fields:
        frappe.logger().warning("No valid fields specified for membership dues schedule lookup")
        return None

    try:
        schedule_info = frappe.db.get_value(
            "Membership Dues Schedule",
            {"membership": membership_name},
            valid_fields,
            as_dict=True,
        )

        return schedule_info

    except Exception as e:
        frappe.logger().error(f"Error looking up dues schedule for membership {membership_name}: {str(e)}")
        return None


def get_dues_schedule_for_membership_name(membership_name: str) -> Optional[str]:
    """
    Get dues schedule name for a specific membership (simplified version).

    Args:
        membership_name: Membership document name/ID

    Returns:
        Schedule name/ID if found, None otherwise

    Examples:
        >>> schedule_name = get_dues_schedule_for_membership_name("MEMB-2025-00123")
    """
    if not membership_name:
        frappe.logger().warning("get_dues_schedule_for_membership_name called with empty membership_name")
        return None

    try:
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"membership": membership_name},
            "name",
        )

        return schedule_name

    except Exception as e:
        frappe.logger().error(
            f"Error looking up dues schedule name for membership {membership_name}: {str(e)}"
        )
        return None
