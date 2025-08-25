#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def check_custom_fields():
    """Check custom fields for specific DocTypes"""

    # DocTypes to check
    doctypes = ["Sales Invoice", "Member", "Membership Dues Schedule"]

    results = {}

    for doctype in doctypes:
        print(f"\n=== Custom Fields for {doctype} ===")

        # Get all custom fields for this doctype
        custom_fields = frappe.get_all(
            "Custom Field",
            filters={"dt": doctype},
            fields=["fieldname", "label", "fieldtype", "options", "reqd", "read_only"],
            order_by="idx",
        )

        results[doctype] = custom_fields

        if custom_fields:
            for field in custom_fields:
                print(f"  - {field.fieldname} ({field.fieldtype}) - {field.label}")
                if field.options:
                    print(f"    Options: {field.options}")
                if field.reqd:
                    print("    Required: Yes")
                if field.read_only:
                    print("    Read Only: Yes")
        else:
            print(f"  No custom fields found for {doctype}")

    # Also check for specific problem fields
    print("\n=== Checking Specific Problem Fields ===")

    # Check Sales Invoice for membership field
    si_fields = frappe.db.sql(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'tabSales Invoice'
        AND column_name LIKE '%membership%'
    """,
        as_dict=True,
    )

    print(f"Sales Invoice membership-related fields: {[f.column_name for f in si_fields]}")

    # Check Member for dues_schedule_template
    member_fields = frappe.db.sql(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'tabMember'
        AND column_name LIKE '%dues%'
    """,
        as_dict=True,
    )

    print(f"Member dues-related fields: {[f.column_name for f in member_fields]}")

    return results


if __name__ == "__main__":
    check_custom_fields()
