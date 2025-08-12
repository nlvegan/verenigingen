#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def add_missing_email_settings_fields():
    """Add missing email settings fields to Verenigingen Settings"""

    # Check if fields already exist
    settings_meta = frappe.get_meta("Verenigingen Settings")
    existing_fields = [f.fieldname for f in settings_meta.fields]

    fields_to_add = [
        {
            "fieldname": "enable_email_group_sync",
            "fieldtype": "Check",
            "label": "Enable Email Group Sync",
            "description": "Enable automatic synchronization of email groups",
            "default": "0",
        },
        {
            "fieldname": "enable_email_analytics",
            "fieldtype": "Check",
            "label": "Enable Email Analytics",
            "description": "Enable email campaign analytics tracking",
            "default": "0",
        },
    ]

    added_fields = []

    for field_def in fields_to_add:
        if field_def["fieldname"] not in existing_fields:
            try:
                # Create custom field
                custom_field = frappe.get_doc(
                    {
                        "doctype": "Custom Field",
                        "dt": "Verenigingen Settings",
                        "fieldname": field_def["fieldname"],
                        "fieldtype": field_def["fieldtype"],
                        "label": field_def["label"],
                        "description": field_def["description"],
                        "default": field_def["default"],
                        "insert_after": "monitoring_section",  # Add in monitoring section
                    }
                )

                custom_field.insert(ignore_permissions=True)
                added_fields.append(field_def["fieldname"])
                print(f"Added field: {field_def['fieldname']}")

            except Exception as e:
                print(f"Failed to add {field_def['fieldname']}: {str(e)}")
        else:
            print(f"Field {field_def['fieldname']} already exists")

    if added_fields:
        frappe.db.commit()

    return {
        "success": True,
        "added_fields": added_fields,
        "message": f"Added {len(added_fields)} new fields to Verenigingen Settings",
    }
