#!/usr/bin/env python3

import frappe


def check_and_create_email_templates():
    """Check if membership email templates exist and create them if needed"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Check existing templates
    existing_templates = frappe.get_all(
        "Email Template", filters={"name": ["like", "membership_%"]}, fields=["name", "subject"]
    )

    print(f"Found {len(existing_templates)} existing membership email templates:")
    for template in existing_templates:
        print(f"  - {template.name}: {template.subject}")

    # Import the create function and run it
    try:
        from verenigingen.api.membership_application_review import create_default_email_templates

        result = create_default_email_templates()
        print(f"\nTemplate creation result: {result}")

        # Check again after creation
        new_templates = frappe.get_all(
            "Email Template", filters={"name": ["like", "membership_%"]}, fields=["name", "subject"]
        )

        print(f"\nAfter creation - Found {len(new_templates)} membership email templates:")
        for template in new_templates:
            print(f"  - {template.name}: {template.subject}")

    except Exception as e:
        print(f"Error creating templates: {str(e)}")

    frappe.destroy()


if __name__ == "__main__":
    check_and_create_email_templates()
