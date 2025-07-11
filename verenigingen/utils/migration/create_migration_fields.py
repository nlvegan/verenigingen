"""
Create required custom fields for eBoekhouden migration
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


@frappe.whitelist()
def create_eboekhouden_migration_fields():
    """Create custom fields required for eBoekhouden migration"""

    custom_fields = {
        "Sales Invoice": [
            {
                "fieldname": "eboekhouden_mutation_nr",
                "label": "E-Boekhouden Mutation Nr",
                "fieldtype": "Data",
                "insert_after": "posting_date",
                "read_only": 1,
                "unique": 1,
                "description": "E-Boekhouden mutation number for tracking",
            }
        ],
        "Purchase Invoice": [
            {
                "fieldname": "eboekhouden_mutation_nr",
                "label": "E-Boekhouden Mutation Nr",
                "fieldtype": "Data",
                "insert_after": "posting_date",
                "read_only": 1,
                "unique": 1,
                "description": "E-Boekhouden mutation number for tracking",
            }
        ],
        "Payment Entry": [
            {
                "fieldname": "eboekhouden_mutation_nr",
                "label": "E-Boekhouden Mutation Nr",
                "fieldtype": "Data",
                "insert_after": "posting_date",
                "read_only": 1,
                "unique": 1,
                "description": "E-Boekhouden mutation number for tracking",
            }
        ],
        "Journal Entry": [
            {
                "fieldname": "eboekhouden_mutation_nr",
                "label": "E-Boekhouden Mutation Nr",
                "fieldtype": "Data",
                "insert_after": "posting_date",
                "read_only": 1,
                "unique": 1,
                "description": "E-Boekhouden mutation number for tracking",
            }
        ],
    }

    try:
        create_custom_fields(custom_fields)
        frappe.db.commit()

        return {
            "success": True,
            "message": "Successfully created E-Boekhouden migration fields",
            "fields_created": list(custom_fields.keys()),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_migration_fields():
    """Check if migration fields exist"""

    doctypes = ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"]
    results = {}

    for doctype in doctypes:
        has_field = frappe.db.has_column(doctype, "eboekhouden_mutation_nr")
        results[doctype] = has_field

    return {"fields_exist": results, "all_exist": all(results.values())}
