import frappe


@frappe.whitelist()
def cleanup_duplicate_test_data():
    """Clean up duplicate test data that causes test failures"""

    # Delete duplicate volunteer record
    frappe.db.sql("DELETE FROM tabVolunteer WHERE name = 'Helper Function Test'")

    # Also clean up any related test members
    frappe.db.sql("DELETE FROM tabMember WHERE email LIKE '%helper.function.test%'")

    frappe.db.commit()

    return {"status": "success", "message": "Test data cleaned up"}
