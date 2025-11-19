#!/usr/bin/env python3
"""
Migration script to add email opt-out field to Member DocType

Run with:
bench --site dev.veganisme.net execute verenigingen.migrations.add_email_opt_out_field.execute
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    """Add email opt-out field to Member DocType"""

    # Define the custom field
    custom_fields = {
        "Member": [
            {
                "fieldname": "communication_preferences_section",
                "fieldtype": "Section Break",
                "label": "Communication Preferences",
                "insert_after": "email",
                "collapsible": 0,
            },
            {
                "fieldname": "opt_out_optional_emails",
                "fieldtype": "Check",
                "label": "Opt-out of Optional Communications",
                "default": "0",  # Default to opted-in
                "insert_after": "communication_preferences_section",
                "description": "Opt out of newsletters and optional organizational emails. Note: Legal communications such as AGM invitations cannot be opted out.",
            },
            {
                "fieldname": "communication_preferences_column",
                "fieldtype": "Column Break",
                "insert_after": "opt_out_optional_emails",
            },
            {
                "fieldname": "communication_preferences_note",
                "fieldtype": "HTML",
                "label": "Legal Notice",
                "insert_after": "communication_preferences_column",
                "options": """
                <div class="alert alert-info">
                    <strong>Important Legal Notice:</strong><br>
                    As a member, you will receive certain legally required communications that cannot be opted out of:
                    <ul style="margin-top: 10px;">
                        <li>Annual General Meeting (AGM) invitations and notices</li>
                        <li>Extraordinary General Meeting notices</li>
                        <li>Statutory voting communications</li>
                        <li>Membership dues and payment notices</li>
                    </ul>
                </div>
                """,
            },
        ]
    }

    # Create the custom fields
    print("Creating custom fields for Member DocType...")
    create_custom_fields(custom_fields, update=True)

    # Set default value for existing members (opted-in by default)
    print("Setting default values for existing members...")
    frappe.db.sql(
        """
        UPDATE `tabMember`
        SET opt_out_optional_emails = 0
        WHERE opt_out_optional_emails IS NULL
    """
    )

    frappe.db.commit()
    print("✅ Email opt-out field added successfully to Member DocType")

    # Clear cache
    frappe.clear_cache()

    return True


if __name__ == "__main__":
    execute()
