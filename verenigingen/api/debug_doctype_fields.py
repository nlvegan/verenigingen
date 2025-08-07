"""
Debug DocType fields to see what's happening with use_enhanced_migration
"""

import frappe


@frappe.whitelist()
def debug_migration_doctype():
    """Debug the E-Boekhouden Migration DocType fields"""

    migration_meta = frappe.get_meta("E-Boekhouden Migration")

    all_fields = []
    for field in migration_meta.fields:
        all_fields.append(
            {"fieldname": field.fieldname, "fieldtype": field.fieldtype, "label": field.label or ""}
        )

    # Check specifically for use_enhanced_migration
    enhanced_field = None
    for field in migration_meta.fields:
        if field.fieldname == "use_enhanced_migration":
            enhanced_field = {
                "fieldname": field.fieldname,
                "fieldtype": field.fieldtype,
                "label": field.label,
                "hidden": getattr(field, "hidden", 0),
                "description": getattr(field, "description", ""),
            }
            break

    return {
        "total_fields": len(all_fields),
        "all_fieldnames": [f["fieldname"] for f in all_fields],
        "enhanced_field_found": enhanced_field is not None,
        "enhanced_field_details": enhanced_field,
        "doctype_name": migration_meta.name,
        "doctype_module": migration_meta.module,
    }
