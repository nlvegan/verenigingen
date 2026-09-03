"""
Dutch Name Utilities
Handles Dutch naming conventions including tussenvoegsels
"""

import frappe
from frappe.utils import cint

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
    high_security_api,
    public_api,
    standard_api,
)

SETTINGS_DOCTYPE = "Verenigingen Settings"
DUTCH_NAME_FIELDS_FIELD = "enable_dutch_name_fields"


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.UTILITY)
def is_dutch_installation():
    """Whether to OFFER the tussenvoegsel field on forms and provision it on User.

    This decides *display and provisioning only*. Nothing that writes a stored name
    consults it any more (#780/#786): a populated tussenvoegsel is itself the
    declaration, and `update_member_full_name` honours it per record. So a member
    with "van" in their name keeps it whatever this setting says.

    It used to answer from a Redis-cached scan for any Company row with country
    "Netherlands" -- memoized for an hour by whichever caller ran first, and cached
    as False for five minutes after any exception. That made a site-wide display
    decision depend on which request or test ran first, and it silently turned
    itself off for five minutes after any transient database error.

    Reading the setting has no such staleness: `get_single_value` caches in the
    per-request `frappe.local.value_cache`, which `set_single_value` and an ordinary
    save both invalidate.
    """
    if not frappe.get_meta(SETTINGS_DOCTYPE).has_field(DUTCH_NAME_FIELDS_FIELD):
        # Code deployed ahead of `bench migrate`. Offer the field rather than
        # silently hiding it: a visible empty input is recoverable, a missing one
        # loses a name particle at the only moment it can be captured.
        return True

    return bool(cint(frappe.db.get_single_value(SETTINGS_DOCTYPE, DUTCH_NAME_FIELDS_FIELD)))


def get_full_last_name(last_name, tussenvoegsel=None):
    """Combine tussenvoegsel and last name for Dutch names"""
    if not tussenvoegsel:
        return last_name

    # Clean up tussenvoegsel (remove extra spaces)
    tussenvoegsel = tussenvoegsel.strip()
    if not tussenvoegsel:
        return last_name

    # Combine with proper spacing
    return f"{tussenvoegsel} {last_name}".strip()


def get_sort_name(first_name, tussenvoegsel=None, last_name=None):
    """
    Generate sorting name for Dutch names following Dutch alphabetization rules.

    Dutch names are sorted by surname without tussenvoegsel, with tussenvoegsel
    appearing after the first name.

    Examples:
        - "Jan van der Berg" → "Berg, Jan van der"
        - "Anna ter Beek" → "Beek, Anna ter"
        - "Maria de Jong" → "Jong, Maria de"
        - "Piet Jansen" (no tussenvoegsel) → "Jansen, Piet"

    Args:
        first_name: First name
        tussenvoegsel: Dutch name particle (van, de, ter, etc.)
        last_name: Surname (without tussenvoegsel)

    Returns:
        Formatted sort name string
    """
    if not last_name:
        return first_name or ""

    if not first_name:
        return get_full_last_name(last_name, tussenvoegsel)

    # If tussenvoegsel exists, sort by bare last name with tussenvoegsel after first name
    if tussenvoegsel and tussenvoegsel.strip():
        return f"{last_name}, {first_name} {tussenvoegsel.strip()}"

    # No tussenvoegsel: simple "Last, First" format
    return f"{last_name}, {first_name}"


@frappe.whitelist()
def format_dutch_full_name(
    first_name: str, middle_name: str | None = None, tussenvoegsel=None, last_name: str | None = None
):
    """
    Format a complete Dutch name with proper tussenvoegsel handling

    No rate limiting - this is just name formatting, not a sensitive operation.
    """
    parts = []

    if first_name:
        parts.append(first_name.strip())

    if middle_name:
        parts.append(middle_name.strip())

    # Add tussenvoegsel + last name as combined last name
    full_last_name = get_full_last_name(last_name, tussenvoegsel)
    if full_last_name:
        parts.append(full_last_name)

    return " ".join(parts)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def setup_dutch_name_fields():
    """Setup tussenvoegsel custom field for User doctype if Dutch installation"""
    if not is_dutch_installation():
        return {"message": "Not a Dutch installation, skipping tussenvoegsel field setup"}

    # Check if field already exists
    existing = frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "tussenvoegsel"})

    if existing:
        return {"message": "Tussenvoegsel field already exists"}

    # Create custom field for User doctype
    custom_field = frappe.get_doc(
        {
            "doctype": "Custom Field",
            "dt": "User",
            "fieldname": "tussenvoegsel",
            "fieldtype": "Data",
            "label": "Tussenvoegsel",
            "description": "Dutch name particles (van, de, van der, etc.)",
            "insert_after": "middle_name",
            "translatable": 0,
            # Deliberately no depends_on. The previous one re-implemented the very
            # Company-country scan this flag stopped using (#780) -- client-side, where
            # it could not see the setting -- and it could never have worked anyway:
            # `frappe.defaults.get_defaults` does not exist in frappe's client JS (it
            # exposes get_default / get_user_default / get_global_default), so the eval
            # threw a TypeError, which form/layout.js turns into an "Invalid depends_on
            # expression" dialog on every User form load. Whether this field exists is
            # already decided above by is_dutch_installation(); if the setting is later
            # turned off, the field stays visible and empty, which is the recoverable
            # direction.
        }
    )

    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
    result = secure_document_operation(
        operation="insert",
        doc=custom_field,
        justification="Create tussenvoegsel custom field for Dutch installation - localization support for Dutch naming conventions",
        required_permissions=["Custom Field:create"],
    )

    if result.success:
        frappe.db.commit()
        return {"message": "Tussenvoegsel field created successfully"}
    else:
        frappe.log_error(f"Failed to create tussenvoegsel custom field: {'; '.join(result.errors)}")
        return {"error": f"Failed to create field: {'; '.join(result.errors)}"}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_dutch_name_formatting():
    """Test function for Dutch name formatting"""
    test_cases = [
        ("Jan", None, "van", "Berg"),
        ("Marie", "Elisabeth", "de", "Vries"),
        ("Pieter", None, "van der", "Meer"),
        ("Anna", "Sophie", None, "Jansen"),
    ]

    results = []
    for first, middle, tussen, last in test_cases:
        formatted = format_dutch_full_name(first, middle, tussen, last)
        full_last = get_full_last_name(last, tussen)
        results.append(
            {
                "input": "first='{first}', middle='{middle}', tussen='{tussen}', last='{last}'",
                "full_name": formatted,
                "combined_last_name": full_last,
            }
        )

    return {"is_dutch": is_dutch_installation(), "test_results": results}
