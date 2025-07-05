"""
Create custom fields for E-Boekhouden migration tracking
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def create_eboekhouden_tracking_fields():
    """Create custom fields for tracking E-Boekhouden data"""

    custom_fields = {
        "Sales Invoice": [
            {
                "fieldname": "eboekhouden_invoice_number",
                "label": "E-Boekhouden Invoice Number",
                "fieldtype": "Data",
                "insert_after": "naming_series",
                "unique": 1,
                "allow_on_submit": 1,
            }
        ],
        "Purchase Invoice": [
            {
                "fieldname": "eboekhouden_invoice_number",
                "label": "E-Boekhouden Invoice Number",
                "fieldtype": "Data",
                "insert_after": "naming_series",
                "unique": 1,
                "allow_on_submit": 1,
            }
        ],
        "Customer": [
            {
                "fieldname": "eboekhouden_relation_code",
                "label": "E-Boekhouden Relation Code",
                "fieldtype": "Data",
                "insert_after": "customer_name",
                "unique": 1,
            }
        ],
        "Supplier": [
            {
                "fieldname": "eboekhouden_relation_code",
                "label": "E-Boekhouden Relation Code",
                "fieldtype": "Data",
                "insert_after": "supplier_name",
                "unique": 1,
            }
        ],
        "Journal Entry": [
            {
                "fieldname": "eboekhouden_mutation_nr",
                "label": "E-Boekhouden Mutation Number",
                "fieldtype": "Data",
                "insert_after": "naming_series",
                "unique": 1,
                "allow_on_submit": 1,
            }
        ],
        "Payment Entry": [
            {
                "fieldname": "eboekhouden_mutation_nr",
                "label": "E-Boekhouden Mutation Number",
                "fieldtype": "Data",
                "insert_after": "naming_series",
                "unique": 1,
                "allow_on_submit": 1,
            }
        ],
    }

    try:
        create_custom_fields(custom_fields, ignore_validate=True)
        frappe.db.commit()
        return {"success": True, "message": "Custom fields created successfully"}
    except Exception as e:
        frappe.log_error(f"Failed to create custom fields: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def ensure_eboekhouden_fields():
    """Ensure all E-Boekhouden tracking fields exist"""
    return create_eboekhouden_tracking_fields()


if __name__ == "__main__":
    result = create_eboekhouden_tracking_fields()
    print(result)
