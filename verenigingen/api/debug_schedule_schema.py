import frappe


@frappe.whitelist()
def check_dues_schedule_fields():
    """Check what fields exist in Membership Dues Schedule table"""

    try:
        # Get field list from database
        result = frappe.db.sql("DESCRIBE `tabMembership Dues Schedule`", as_dict=True)

        field_names = [field["Field"] for field in result]

        # Check if membership field exists
        has_membership_field = "membership" in field_names

        # Look for similar fields
        membership_related_fields = [f for f in field_names if "member" in f.lower()]

        return {
            "total_fields": len(field_names),
            "has_membership_field": has_membership_field,
            "membership_related_fields": membership_related_fields,
            "all_fields": field_names[:20],  # First 20 fields
            "schema": result[:10] if result else [],  # First 10 field definitions
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def check_schedule_doctype_meta():
    """Check DocType meta information for Membership Dues Schedule"""

    try:
        meta = frappe.get_meta("Membership Dues Schedule")

        # Get all field names
        field_names = [field.fieldname for field in meta.fields]

        # Look for membership-related fields
        membership_fields = []
        for field in meta.fields:
            if "member" in field.fieldname.lower():
                membership_fields.append(
                    {
                        "fieldname": field.fieldname,
                        "fieldtype": field.fieldtype,
                        "label": field.label,
                        "options": getattr(field, "options", None),
                        "read_only": getattr(field, "read_only", 0),
                    }
                )

        return {
            "doctype": "Membership Dues Schedule",
            "total_fields": len(field_names),
            "has_membership_field": "membership" in field_names,
            "membership_related_fields": membership_fields,
            "first_10_fields": field_names[:10],
        }

    except Exception as e:
        return {"error": str(e)}
