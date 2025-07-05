"""
Patch to create E-Boekhouden custom fields
This ensures the fields exist before any migration code tries to use them
"""

import frappe


def execute():
    """Create E-Boekhouden custom fields if they don't exist"""

    try:
        from verenigingen.utils.create_eboekhouden_custom_fields import create_eboekhouden_tracking_fields

        # Check if fields already exist
        payment_field_exists = frappe.db.exists(
            "Custom Field", {"dt": "Payment Entry", "fieldname": "eboekhouden_mutation_nr"}
        )

        journal_field_exists = frappe.db.exists(
            "Custom Field", {"dt": "Journal Entry", "fieldname": "eboekhouden_mutation_nr"}
        )

        if not payment_field_exists or not journal_field_exists:
            print("Creating E-Boekhouden custom fields...")
            result = create_eboekhouden_tracking_fields()

            if result.get("success"):
                print("✅ E-Boekhouden custom fields created successfully")
            else:
                print(f"❌ Failed to create custom fields: {result.get('error')}")
        else:
            print("✅ E-Boekhouden custom fields already exist")

    except Exception as e:
        print(f"❌ Error in patch: {str(e)}")
        # Don't fail the patch if there are issues
        frappe.log_error(f"E-Boekhouden fields patch error: {str(e)}")
