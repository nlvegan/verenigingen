"""
CSV Data Transformers

Pure functions for cleaning, validating, and transforming CSV data during import.
Extracted from MijnroodCSVImport to improve testability and reusability.

All functions are stateless and have no side effects (except logging).
"""

import re
from datetime import datetime
from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate


def clean_value(value: str, field_type: str) -> Any:
    """
    Clean and convert values based on field type.

    Args:
        value: Raw string value from CSV
        field_type: Type of field (e.g., 'email', 'contact_number', 'birth_date')

    Returns:
        Cleaned and converted value appropriate for the field type

    Raises:
        frappe.ValidationError: If value contains dangerous content or is too long
    """
    if not value or value.strip() == "":
        return None

    value = value.strip()

    # Handle common "no data" indicators - convert to None
    if value in ["-", "N/A", "n/a", "N.A.", "n.a.", "NULL", "null", "UNKNOWN", "unknown", "?"]:
        return None

    # SECURITY: Prevent CSV injection attacks - reject dangerous content
    # Allow phone numbers with + prefix (e.g., +31), but block formula injections
    is_phone_number = field_type == "contact_number" and value.startswith("+") and value[1:2].isdigit()

    if not is_phone_number and (
        value.startswith(("=", "@", "\t", "\r"))
        or (value.startswith(("-", "+")) and not value[1:2].isdigit())
    ):
        frappe.throw(
            _(
                "Security: Field contains potentially dangerous content that could be interpreted as formula: {0}"
            ).format(value[:50])
        )

    # SECURITY: Limit field length to prevent memory issues
    if len(value) > 2000:  # Reasonable limit for most fields
        frappe.throw(_("Field value too long (max 2000 characters): {0}").format(value[:50] + "..."))

    # Date fields
    if field_type in ["birth_date", "member_since"]:
        return parse_date(value)

    # Currency fields
    elif field_type in ["dues_rate"]:
        return flt(re.sub(r"[^\d.,]", "", value).replace(",", "."))

    # Boolean fields
    elif field_type in ["privacy_accepted"]:
        return value.lower() in ["ja", "yes", "1", "true", "waar"]

    # IBAN cleaning
    elif field_type == "iban":
        return re.sub(r"\s+", "", value.upper())

    # Email cleaning
    elif field_type == "email":
        return value.lower()

    # Phone number cleaning
    elif field_type == "contact_number":
        return clean_phone_number(value)

    # Country code conversion
    elif field_type == "country":
        return convert_country_code(value)

    # Membership type conversion
    elif field_type == "membership_type":
        return convert_membership_type(value)

    return cstr(value)


def convert_country_code(country_code: str) -> str:
    """
    Convert country codes to full country names.

    Args:
        country_code: Two-letter ISO country code (e.g., 'NL', 'BE')

    Returns:
        Full country name (e.g., 'Netherlands', 'Belgium')
        Returns original code if no mapping found
    """
    country_mapping = {
        "NL": "Netherlands",
        "BE": "Belgium",
        "DE": "Germany",
        "FR": "France",
        "ES": "Spain",
        "IT": "Italy",
        "SE": "Sweden",
        "NO": "Norway",
        "DK": "Denmark",
        "FI": "Finland",
        "AT": "Austria",
        "CH": "Switzerland",
        "LU": "Luxembourg",
        "GB": "United Kingdom",
        "UK": "United Kingdom",
        "US": "United States",
        "CA": "Canada",
        "AU": "Australia",
    }

    code = country_code.upper().strip()
    return country_mapping.get(code, country_code)  # Return original if not found


def clean_phone_number(phone_number: str) -> str:
    """
    Clean and normalize phone number format for validation compatibility.

    Handles Dutch-specific formatting and converts international numbers
    to national format where appropriate.

    Args:
        phone_number: Raw phone number from CSV

    Returns:
        Cleaned phone number in standardized format, or empty string if invalid

    Example:
        "+31 6 12345678" → "0612345678"
        "+31 20 1234567" → "0201234567"
        "06-1234-5678" → "0612345678"
    """
    if not phone_number:
        return ""

    # Remove extra whitespace
    phone = phone_number.strip()

    # Step 1: Normalize common formats
    if phone.startswith("+"):
        # Remove spaces in international numbers but keep the + prefix
        phone = "+" + "".join(phone[1:].split())
    else:
        # For non-international numbers, just remove spaces and dashes
        phone = "".join(phone.split()).replace("-", "")

    # Step 2: Apply Dutch-specific normalization rules
    if phone.startswith("+316") and len(phone) == 12:  # Dutch mobile
        # Convert to national format for better compatibility
        phone = "0" + phone[3:]  # +31612345678 → 0612345678
    elif phone.startswith("+3120") or phone.startswith("+3130"):  # Dutch landline
        # Convert to national format
        phone = "0" + phone[3:]  # +31201234567 → 0201234567

    # Step 3: Validate length and format for Dutch numbers
    if phone.startswith("06") and len(phone) == 10:  # Dutch mobile
        return phone
    elif phone.startswith("0") and len(phone) >= 9 and len(phone) <= 10:  # Dutch landline
        return phone
    elif phone.startswith("+") and len(phone) >= 10 and len(phone) <= 15:  # International
        return phone
    else:
        # Invalid format - return empty string to skip this field
        frappe.logger().warning("Invalid phone number format during CSV import: %s", phone_number)
        return ""


def convert_membership_type(membership_type: str) -> str:
    """
    Convert Dutch membership types to standardized values.

    Maps Mijnrood status types to internal representation:
    - 'Lid' → Standard (Active member)
    - 'Overleden' → Deceased
    - 'Opgezegd' → Terminated (Voluntarily)
    - 'Geroyeerd' → Expelled
    - 'Dubbel' → Duplicate (rejected application)

    Args:
        membership_type: Raw membership type from CSV

    Returns:
        Standardized membership type, or original value if no mapping exists
    """
    type_mapping = {
        "lid": "Standard",  # Active regular member
        "aspirant": "Aspirant",  # Candidate/provisional member
        "overleden": "Deceased",  # Deceased member
        "opgezegd": "Terminated",  # Voluntarily cancelled membership
        "geroyeerd": "Expelled",  # Expelled/banned from organization
        "dubbel": "Duplicate",  # Duplicate entry (should be rejected)
        "uitgeschreven": "Terminated",  # Unsubscribed/left voluntarily (legacy)
        "geschorst": "Suspended",  # Suspended (legacy)
    }

    type_value = membership_type.lower().strip() if membership_type else ""
    return type_mapping.get(type_value, membership_type)  # Return original if not found


def parse_date(date_str: str) -> Optional[str]:
    """
    Parse date string to YYYY-MM-DD format.

    Tries multiple common date formats to handle various CSV sources.

    Args:
        date_str: Date string in various possible formats

    Returns:
        Date in YYYY-MM-DD format, or None if parsing fails

    Example:
        "31-12-2023" → "2023-12-31"
        "2023/12/31" → "2023-12-31"
        "12/31/2023" → "2023-12-31"
    """
    if not date_str:
        return None

    # Try different date formats
    formats = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"]

    for fmt in formats:
        try:
            return getdate(date_str).strftime("%Y-%m-%d")
        except (ValueError, TypeError, frappe.ValidationError):
            continue

    return None


# Payment Period and Membership Type Utilities


def map_payment_period_to_billing_frequency(payment_period: str) -> str:
    """
    Map Dutch payment period terms to billing frequencies.

    Args:
        payment_period: Dutch payment period string (e.g., 'Maandelijks', 'Jaarlijks')

    Returns:
        Billing frequency (Monthly, Quarterly, Semi-Annual, Annual)
        Defaults to Annual if not found

    Example:
        "Maandelijks" → "Monthly"
        "Kwartaal" → "Quarterly"
        "Jaarlijks" → "Annual"
    """
    # Payment period mapping (Dutch → English)
    payment_period_mapping = {
        "maandelijks": "Monthly",
        "monthly": "Monthly",
        "per maand": "Monthly",
        "kwartaal": "Quarterly",
        "quarterly": "Quarterly",
        "per kwartaal": "Quarterly",
        "driemaandelijks": "Quarterly",
        "halfjaar": "Semi-Annual",
        "halfjaarlijks": "Semi-Annual",
        "semi-annual": "Semi-Annual",
        "per halfjaar": "Semi-Annual",
        "jaar": "Annual",
        "jaarlijks": "Annual",
        "annual": "Annual",
        "per jaar": "Annual",
    }

    if not payment_period:
        return "Annual"

    # Normalize and lookup
    normalized = payment_period.lower().strip()
    return payment_period_mapping.get(normalized, "Annual")


def determine_membership_type_from_payment_period(row_data: dict) -> str:
    """
    Determine membership type from payment period or settings default.

    NOTE: CSV's membership_type column maps to Member.status, NOT Membership Type.
    This function determines the Verenigingen Membership Type for billing purposes.

    Args:
        row_data: CSV row data with payment_period field

    Returns:
        Membership type name

    Priority:
        1. Map payment_period to membership type (Monthly/Quarterly/Annual) from settings
        2. Settings default membership type
        3. Fail loudly with clear error message

    Raises:
        frappe.ValidationError: If membership type cannot be determined

    Example:
        row_data = {"payment_period": "Maandelijks"}
        → Returns settings.csv_monthly_membership_type
    """
    # Priority 1: Map payment period to membership type from settings
    if row_data and row_data.get("payment_period"):
        payment_period = row_data["payment_period"].lower().strip()
        settings = frappe.get_single("Verenigingen Settings")

        if payment_period in ["maandelijks", "monthly", "per maand"]:
            if settings.csv_monthly_membership_type:
                return settings.csv_monthly_membership_type
            else:
                frappe.throw(
                    "Payment period is 'Maandelijks' but no CSV Monthly Membership Type is configured in Verenigingen Settings. "
                    "Please set the 'CSV Monthly Membership Type' field."
                )
        elif payment_period in ["kwartaal", "quarterly", "per kwartaal", "driemaandelijks"]:
            if settings.csv_quarterly_membership_type:
                return settings.csv_quarterly_membership_type
            else:
                frappe.throw(
                    "Payment period is 'Kwartaal' but no CSV Quarterly Membership Type is configured in Verenigingen Settings. "
                    "Please set the 'CSV Quarterly Membership Type' field."
                )
        elif payment_period in ["halfjaar", "halfjaarlijks", "semi-annual", "per halfjaar"]:
            frappe.throw(
                f"Payment period '{payment_period}' maps to Semi-Annual membership, "
                "but there is no CSV Semi-Annual Membership Type setting. "
                "Please add this field to Verenigingen Settings or change the payment period."
            )
        elif payment_period in ["jaar", "jaarlijks", "annual", "per jaar"]:
            if settings.csv_annual_membership_type:
                return settings.csv_annual_membership_type
            else:
                frappe.throw(
                    "Payment period is 'Jaarlijks' but no CSV Annual Membership Type is configured in Verenigingen Settings. "
                    "Please set the 'CSV Annual Membership Type' field."
                )

    # Priority 2: Get default from settings
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if settings and settings.default_membership_type:
            if not frappe.db.exists("Membership Type", settings.default_membership_type):
                frappe.throw(
                    f"Default membership type '{settings.default_membership_type}' from settings does not exist"
                )
            return settings.default_membership_type
    except Exception as e:
        frappe.logger().warning("Could not get default membership type from settings: %s", str(e))

    # NO FALLBACK - fail loudly with member context
    member_id = row_data.get("member_id", "") if row_data else ""
    payment_period_value = row_data.get("payment_period") if row_data else None
    frappe.throw(
        f"Cannot determine membership type for member {member_id}. "
        f"Payment period: '{payment_period_value}', no default membership type configured. "
        f"Either provide a valid payment period in CSV or set a default membership type in Verenigingen Settings."
    )


def calculate_next_invoice_date(start_date, billing_frequency: str) -> str:
    """
    Calculate next invoice date based on start date and billing frequency.

    Args:
        start_date: Starting date for calculation (date object or string)
        billing_frequency: Monthly, Quarterly, Semi-Annual, or Annual

    Returns:
        Next invoice date in YYYY-MM-DD format

    Example:
        calculate_next_invoice_date(date(2024, 1, 1), "Monthly")
        → "2024-02-01"
    """
    from datetime import date

    from dateutil.relativedelta import relativedelta

    # Convert to date object if string
    if isinstance(start_date, str):
        start_date = getdate(start_date)

    if billing_frequency == "Monthly":
        next_date = start_date + relativedelta(months=1)
    elif billing_frequency == "Quarterly":
        next_date = start_date + relativedelta(months=3)
    elif billing_frequency == "Semi-Annual":
        next_date = start_date + relativedelta(months=6)
    elif billing_frequency == "Annual":
        next_date = start_date + relativedelta(months=12)
    else:
        # Default to annual
        next_date = start_date + relativedelta(months=12)

    return next_date.strftime("%Y-%m-%d")
