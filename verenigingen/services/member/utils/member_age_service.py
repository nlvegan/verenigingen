"""
Member Age Service - Centralized age calculation and validation utilities.

This service provides all age-related functionality that was previously scattered
in the Member DocType. Extracted for better maintainability and reusability.

Functions:
    - calculate_member_age(): Calculate age based on birth date
    - validate_member_age_requirements(): Validate membership/volunteer age requirements
    - get_age_group(): Get privacy-friendly age group categorization
    - update_member_age_field(): Update the age field on a member document
"""

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import getdate

from verenigingen.utils.service_error_handler import handle_service_error, safe_import


def calculate_member_age(birth_date):
    """Calculate age based on birth_date field.

    Extracted from member.py without modification. Pure utility function
    that can be used by any code needing age calculation.

    Args:
        birth_date: Birth date as string or date object

    Returns:
        int: Age in years, or None if birth_date is invalid
    """
    try:
        if birth_date:
            # Site-tz today, not the server/process date: in the late-UTC window the
            # two name different calendar days, so a member whose birthday is today
            # comes out a year younger (#628).
            today_date = getdate()
            if isinstance(birth_date, str):
                born = datetime.strptime(birth_date, "%Y-%m-%d").date()
            else:
                born = birth_date
            age = today_date.year - born.year - ((today_date.month, today_date.day) < (born.month, born.day))
            return age
        else:
            return None
    except Exception as e:
        handle_service_error(
            e,
            "MemberAgeService",
            "Calculate member age",
            {"birth_date": str(birth_date) if birth_date else "None"},
            raise_error=False,
        )
        return None


def update_member_age_field(member_doc):
    """Update the age field on a member document.

    Extracted from member.py calculate_age() method. Updates the age field
    on the provided member document.

    Args:
        member_doc: Member document instance to update
    """
    try:
        if member_doc.birth_date:
            member_doc.age = calculate_member_age(member_doc.birth_date)
        else:
            member_doc.age = None
    except Exception as e:
        handle_service_error(
            e,
            "MemberAgeService",
            "Update age field",
            {"member": getattr(member_doc, "name", "Unknown")},
            raise_error=False,
        )


def validate_member_age_requirements(member_doc, allow_parental_consent=None):
    """Validate age requirements for membership and volunteering.

    Extracted from member.py with improved parameter handling to reduce coupling.
    Uses the existing AgeValidator utility for consistent validation logic.

    Args:
        member_doc: Member document instance to validate
        allow_parental_consent (bool, optional): Whether to allow parental consent for minors.
            If None, will attempt to determine from member document.
    """
    if not member_doc.birth_date:
        return  # Skip validation if no birth date provided

    try:
        from verenigingen.utils.validation_utilities import AgeValidator
    except ImportError as e:
        handle_service_error(
            e,
            "MemberAgeService",
            "Import AgeValidator",
            {"member": getattr(member_doc, "name", "Unknown")},
            raise_error=False,
            log_level="warning",
        )
        return  # Skip validation if AgeValidator not available

    try:
        # Determine parental consent setting
        if allow_parental_consent is None:
            # Try to determine from member document, but don't require specific method
            if hasattr(member_doc, "is_application_member") and callable(member_doc.is_application_member):
                allow_parental_consent = member_doc.is_application_member()
            elif hasattr(member_doc, "application_status"):
                # Fallback: check if it's an application based on status
                allow_parental_consent = bool(getattr(member_doc, "application_status", ""))
            else:
                # Conservative default: don't allow parental consent
                allow_parental_consent = False

        membership_result = AgeValidator.validate_age(
            member_doc.birth_date,
            context="membership",
            allow_parental_consent=allow_parental_consent,
            throw_on_error=False,
        )

        if not membership_result.is_valid:
            if allow_parental_consent and membership_result.warning:
                # Show warning for applications requiring parental consent
                frappe.msgprint(membership_result.warning)
            else:
                # Throw error for direct member creation or hard validation failures
                frappe.throw(membership_result.message, frappe.ValidationError)
        elif membership_result.warning:
            # Show any warnings (e.g., parental consent required)
            frappe.msgprint(membership_result.warning)

        # Additional validation for volunteering
        if hasattr(member_doc, "interested_in_volunteering") and member_doc.interested_in_volunteering:
            volunteer_result = AgeValidator.validate_age(
                member_doc.birth_date, context="volunteer", throw_on_error=False
            )

            if not volunteer_result.is_valid:
                frappe.throw(volunteer_result.message, frappe.ValidationError)

    except frappe.ValidationError:
        # Age-limit rejections (minimum age from Verenigingen Settings) MUST block the
        # save. Previously the broad except below swallowed this throw, so the rule was
        # dead and under-age members saved silently.
        raise
    except Exception as e:
        handle_service_error(
            e,
            "MemberAgeService",
            "Validate age requirements",
            {"member": getattr(member_doc, "name", "Unknown")},
            raise_error=False,
        )


def get_age_group(birth_date):
    """Get age group for privacy-friendly display using standardized age calculation.

    Extracted from member.py without modification. Uses the AgeValidator
    for consistent age calculation across the system.

    Args:
        birth_date: Birth date as string or date object

    Returns:
        str: Age group category or None if birth_date is invalid
    """
    if not birth_date:
        return None

    try:
        from frappe.utils import getdate, today

        # Bucket on the true integer calendar age, not a days/365.25 float: the
        # latter dips ~0.002 below the integer at an exact birthday (e.g. someone
        # born exactly 18 years ago today computes as 17.998), which would
        # mis-bucket them one group down on certain calendar dates.
        bd = getdate(birth_date)
        ref = getdate(today())
        if bd > ref:
            return None
        age = ref.year - bd.year - ((ref.month, ref.day) < (bd.month, bd.day))

        if age < 18:
            return "Minor"
        elif age < 30:
            return "Young Adult"
        elif age < 50:
            return "Adult"
        elif age < 65:
            return "Middle-aged"
        else:
            return "Senior"
    except Exception:
        return None


def calculate_age_from_string(birth_date_str):
    """Calculate age from birth date string with error handling.

    Convenience function for external code that needs age calculation
    from string inputs with robust error handling.

    Args:
        birth_date_str (str): Birth date in YYYY-MM-DD format

    Returns:
        int: Age in years, or None if invalid
    """
    if not birth_date_str:
        return None

    try:
        birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
        return calculate_member_age(birth_date)
    except (ValueError, TypeError):
        return None


def is_minor(birth_date):
    """Check if a person is under 18 years old.

    Args:
        birth_date: Birth date as string or date object

    Returns:
        bool: True if under 18, False otherwise, None if invalid birth date
    """
    age = calculate_member_age(birth_date)
    return age < 18 if age is not None else None


def is_eligible_for_volunteering(birth_date):
    """Check if a person meets age requirements for volunteering.

    Args:
        birth_date: Birth date as string or date object

    Returns:
        bool: True if eligible, False otherwise, None if invalid birth date
    """
    age = calculate_member_age(birth_date)
    return age >= 16 if age is not None else None  # Standard volunteering age requirement
