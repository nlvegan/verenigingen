"""
Dutch Name Utilities
Handles Dutch naming conventions including tussenvoegsels
"""

import frappe

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
    high_security_api,
    public_api,
    standard_api,
)


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.UTILITY)
def is_dutch_installation():
    """Check if this is a Dutch installation based on company country (cached for performance)"""
    # Use cache to avoid repeated database queries
    cache_key = "is_dutch_installation"
    cached_result = frappe.cache().get_value(cache_key)

    if cached_result is not None:
        return cached_result

    try:
        result = False

        # Check default company
        company = frappe.defaults.get_defaults().get("company")
        if company:
            company_doc = frappe.get_doc("Company", company)
            result = company_doc.country == "Netherlands"

        if not result:
            # Fallback: check all companies
            companies = frappe.get_all("Company", fields=["country"])
            result = any(c.country == "Netherlands" for c in companies)

        # Cache result for 1 hour - this rarely changes
        frappe.cache().set_value(cache_key, result, expires_in_sec=3600)
        return result

    except Exception:
        # Cache False result for shorter time in case of errors
        frappe.cache().set_value(cache_key, False, expires_in_sec=300)  # 5 minutes
        return False


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
            "depends_on": 'eval:frappe.defaults.get_defaults().company && frappe.get_doc("Company", frappe.defaults.get_defaults().company).country === "Netherlands"',
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
