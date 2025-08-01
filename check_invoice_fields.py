#!/usr/bin/env python
import frappe


@frappe.whitelist()
def check_custom_fields():
    """Check custom fields on Sales Invoice"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Get custom fields for Sales Invoice
    custom_fields = frappe.get_all(
        "Custom Field", filters={"dt": "Sales Invoice"}, fields=["fieldname", "label", "fieldtype", "options"]
    )

    print("Custom fields on Sales Invoice:")
    for field in custom_fields:
        print(f"  - {field['fieldname']} ({field['label']}) - Type: {field['fieldtype']}")
        if field.get("options"):
            print(f"    Options: {field['options']}")

    # Also check DocType fields directly
    meta = frappe.get_meta("Sales Invoice")
    all_fields = [f.fieldname for f in meta.fields]

    print("\nChecking for specific fields:")
    fields_to_check = ["membership", "member", "dues_invoice", "is_dues_invoice"]
    for field in fields_to_check:
        if field in all_fields:
            print(f"  ✓ {field} exists")
        else:
            print(f"  ✗ {field} does NOT exist")

    frappe.destroy()


if __name__ == "__main__":
    check_custom_fields()
