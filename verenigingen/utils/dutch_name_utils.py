"""
Dutch Name Utilities
Handles Dutch naming conventions including tussenvoegsels
"""

import frappe


@frappe.whitelist()
def is_dutch_installation():
    """Check if this is a Dutch installation based on company country"""
    try:
        # Check default company
        company = frappe.defaults.get_defaults().get("company")
        if company:
            company_doc = frappe.get_doc("Company", company)
            return company_doc.country == "Netherlands"

        # Fallback: check all companies
        companies = frappe.get_all("Company", fields=["country"])
        return any(c.country == "Netherlands" for c in companies)
    except Exception:
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


@frappe.whitelist()
def format_dutch_full_name(first_name, middle_name=None, tussenvoegsel=None, last_name=None):
    """Format a complete Dutch name with proper tussenvoegsel handling"""
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

    custom_field.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"message": "Tussenvoegsel field created successfully"}


@frappe.whitelist()
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
                "input": f"first='{first}', middle='{middle}', tussen='{tussen}', last='{last}'",
                "full_name": formatted,
                "combined_last_name": full_last,
            }
        )

    return {"is_dutch": is_dutch_installation(), "test_results": results}
