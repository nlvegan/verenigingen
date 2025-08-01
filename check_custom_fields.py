#!/usr/bin/env python3
"""Check for custom fields on Sales Invoice"""

import frappe


def main():
    frappe.init("dev.veganisme.net")

    # Check custom fields on Sales Invoice
    custom_fields = frappe.get_all(
        "Custom Field", filters={"dt": "Sales Invoice"}, fields=["fieldname", "label", "fieldtype", "options"]
    )

    print("Sales Invoice Custom Fields:")
    for field in custom_fields:
        print(f"  {field.fieldname}: {field.label} ({field.fieldtype})")
        if field.options:
            print(f"    Options: {field.options}")

    # Check if membership is a custom field
    membership_field = frappe.db.get_value(
        "Custom Field",
        {"dt": "Sales Invoice", "fieldname": "membership"},
        ["fieldname", "label", "fieldtype", "options"],
        as_dict=True,
    )

    if membership_field:
        print(f"\nMembership field exists: {membership_field}")
    else:
        print("\nNo membership field found on Sales Invoice")


if __name__ == "__main__":
    main()
