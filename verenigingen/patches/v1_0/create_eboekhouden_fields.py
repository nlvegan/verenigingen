"""
Patch to create E-Boekhouden custom fields
This ensures the fields exist before any migration code tries to use them
"""

import frappe


def execute():
    """E-Boekhouden custom fields are now created via fixtures during installation"""

    # Check if fields already exist from fixtures
    payment_field_exists = frappe.db.exists(
        "Custom Field", {"dt": "Payment Entry", "fieldname": "eboekhouden_mutation_nr"}
    )

    journal_field_exists = frappe.db.exists(
        "Custom Field", {"dt": "Journal Entry", "fieldname": "eboekhouden_mutation_nr"}
    )

    if payment_field_exists and journal_field_exists:
        print("✅ E-Boekhouden custom fields exist (created via fixtures)")
    else:
        print("⚠️ E-Boekhouden custom fields missing - should be created via fixtures")
