"""Check E-Boekhouden settings."""

import frappe


@frappe.whitelist()
def check_settings():
    """Check E-Boekhouden settings and payment configuration."""

    # Check if Global Defaults has the company
    company = frappe.db.get_single_value("Global Defaults", "default_company")

    # Check for E-Boekhouden specific settings
    settings_exist = frappe.db.exists("DocType", "E-Boekhouden Settings")

    results = {
        "company": company,
        "settings_doctype_exists": settings_exist,
        "payment_entries_with_kas": 0,
        "payment_entries_with_bank": 0,
    }

    # Count payment entries
    kas_count = frappe.db.count(
        "Payment Entry", {"paid_to": "10000 - Kas - NVV", "eboekhouden_mutation_nr": ["is", "set"]}
    )

    bank_count = frappe.db.count(
        "Payment Entry", {"paid_to": ["like", "%Triodos%"], "eboekhouden_mutation_nr": ["is", "set"]}
    )

    results["payment_entries_with_kas"] = kas_count
    results["payment_entries_with_bank"] = bank_count

    # Check if enhanced processing would work
    results["enhanced_ready"] = company is not None

    return results
