"""
Migration patch to add donor auto-creation fields
"""

import frappe


def execute():
    """Add donor auto-creation configuration fields to Verenigingen Settings"""

    # Check if fields already exist
    doctype_json = frappe.get_meta("Verenigingen Settings")
    existing_fields = [field.fieldname for field in doctype_json.fields]

    fields_to_add = [
        "donations_gl_account",
        "auto_create_donors",
        "donor_customer_groups",
        "minimum_donation_amount",
    ]

    missing_fields = [field for field in fields_to_add if field not in existing_fields]

    if missing_fields:
        frappe.reload_doc("verenigingen", "doctype", "verenigingen_settings")
        frappe.logger().info(f"Added donor auto-creation fields: {missing_fields}")

    # Check if Donor fields exist
    donor_doctype_json = frappe.get_meta("Donor")
    donor_existing_fields = [field.fieldname for field in donor_doctype_json.fields]

    donor_fields_to_add = ["created_from_payment", "creation_trigger_amount"]

    donor_missing_fields = [field for field in donor_fields_to_add if field not in donor_existing_fields]

    if donor_missing_fields:
        frappe.reload_doc("verenigingen", "doctype", "donor")
        frappe.logger().info(f"Added donor tracking fields: {donor_missing_fields}")

    # Update customer_sync_status options if needed
    if "Auto-Created" not in str(frappe.get_meta("Donor").get_field("customer_sync_status").options):
        frappe.reload_doc("verenigingen", "doctype", "donor")
        frappe.logger().info("Updated donor customer_sync_status options")

    frappe.db.commit()
