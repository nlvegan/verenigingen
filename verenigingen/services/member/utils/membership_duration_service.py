"""
Membership Duration Service - Centralized membership duration calculation and formatting.

This service handles all membership duration calculations that were previously
in member.py. Provides reusable utilities for calculating membership periods,
total days, and human-readable duration formatting.

Functions:
    - calculate_total_membership_days(): Calculate total active membership days
    - format_duration_human_readable(): Convert days to readable format
    - update_member_duration_fields(): Update member document with calculated values
"""

import frappe
from frappe.utils import date_diff, getdate, now, today

from verenigingen.utils.service_error_handler import create_service_result, handle_service_error


def calculate_total_membership_days(member_name):
    """Calculate total membership days from all active membership periods.

    Extracted from member.py without modification. Handles complex date calculations
    for different membership statuses (Active, Cancelled, Expired).

    Args:
        member_name (str): Name/ID of the member to calculate for

    Returns:
        int: Total membership days, or 0 if calculation fails
    """
    try:
        if not member_name or not frappe.db.exists("Member", member_name):
            # For new records, can't calculate duration yet
            return 0

        # Get all memberships for this member, ordered by start date
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name, "docstatus": 1},
            fields=["name", "start_date", "renewal_date", "status", "cancellation_date"],
            order_by="start_date asc",
        )

        if not memberships:
            return 0

        total_days = 0
        today_date = getdate(today())

        for membership in memberships:
            start_date = getdate(membership.start_date)

            # Determine end date for this membership period
            if membership.status in ["Cancelled", "Expired"]:
                # Use cancellation date if available, otherwise renewal date
                end_date = (
                    getdate(membership.cancellation_date)
                    if membership.cancellation_date
                    else getdate(membership.renewal_date)
                )
            elif membership.status == "Active":
                # For active memberships, use today or renewal date (whichever is earlier)
                renewal_date = getdate(membership.renewal_date) if membership.renewal_date else today_date
                end_date = min(today_date, renewal_date)
            else:
                # For other statuses, use renewal date if available
                end_date = getdate(membership.renewal_date) if membership.renewal_date else start_date

            # Calculate days for this membership period
            if end_date >= start_date:
                period_days = date_diff(end_date, start_date) + 1  # +1 to include both start and end dates
                total_days += period_days

        return total_days

    except Exception as e:
        handle_service_error(
            e,
            "MembershipDurationService",
            "Calculate total membership days",
            {"member": member_name},
            raise_error=False,
        )
        return 0


def format_duration_human_readable(total_days):
    """Convert total days to human-readable duration format.

    Extracted from member.py calculate_cumulative_membership_duration() method.
    Formats days into years, months, and days with proper pluralization.

    Args:
        total_days (int): Total days to format

    Returns:
        str: Human-readable duration (e.g., "2 years, 3 months, 15 days")
    """
    try:
        if total_days <= 0:
            return "Less than 1 day"

        # Convert total days to human-readable format
        years = total_days // 365
        remaining_days = total_days % 365
        months = remaining_days // 30
        remaining_days = remaining_days % 30

        # Build duration string
        duration_parts = []
        if years > 0:
            duration_parts.append(f"{years} year{'s' if years != 1 else ''}")
        if months > 0:
            duration_parts.append(f"{months} month{'s' if months != 1 else ''}")
        if remaining_days > 0 and years == 0:  # Only show days if less than a year
            duration_parts.append(f"{remaining_days} day{'s' if remaining_days != 1 else ''}")

        if duration_parts:
            return ", ".join(duration_parts)
        else:
            return "Less than 1 day"

    except Exception as e:
        handle_service_error(
            e, "MembershipDurationService", "Format duration", {"total_days": total_days}, raise_error=False
        )
        return "Error calculating duration"


def calculate_duration_in_years(total_days):
    """Calculate duration in years for backward compatibility.

    Args:
        total_days (int): Total days

    Returns:
        float: Duration in years (using 365.25 for leap year accounting)
    """
    try:
        if total_days <= 0:
            return 0
        return total_days / 365.25
    except Exception:
        return 0


def update_member_duration_fields(member_doc):
    """Update member document with calculated duration values.

    Extracted from member.py update_membership_duration() method.
    Updates total_membership_days, cumulative_membership_duration, and last_duration_update.

    Args:
        member_doc: Member document instance to update

    Returns:
        dict: Result with success status and calculated values
    """
    try:
        # Calculate the raw days
        total_days = calculate_total_membership_days(member_doc.name)

        # Update the fields
        member_doc.total_membership_days = total_days
        member_doc.last_duration_update = now()

        # Calculate human-readable format
        member_doc.cumulative_membership_duration = format_duration_human_readable(total_days)

        return create_service_result(
            success=True,
            data={
                "total_days": total_days,
                "duration": member_doc.cumulative_membership_duration,
                "updated": member_doc.last_duration_update,
            },
        )

    except Exception as e:
        error_result = handle_service_error(
            e,
            "MembershipDurationService",
            "Update member duration fields",
            {"member": getattr(member_doc, "name", "Unknown")},
            raise_error=False,
        )
        return error_result


def get_membership_duration_summary(member_name):
    """Get complete membership duration summary for a member.

    Convenience function for external code that needs duration information
    without updating the member document.

    Args:
        member_name (str): Name/ID of the member

    Returns:
        dict: Duration summary with days, formatted duration, and years
    """
    try:
        total_days = calculate_total_membership_days(member_name)

        return {
            "member_name": member_name,
            "total_days": total_days,
            "duration_formatted": format_duration_human_readable(total_days),
            "duration_years": calculate_duration_in_years(total_days),
            "calculation_date": today(),
        }

    except Exception as e:
        handle_service_error(
            e, "MembershipDurationService", "Get duration summary", {"member": member_name}, raise_error=False
        )
        return {
            "member_name": member_name,
            "total_days": 0,
            "duration_formatted": "Error calculating duration",
            "duration_years": 0,
            "calculation_date": today(),
        }
