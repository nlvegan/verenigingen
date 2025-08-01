#!/usr/bin/env python3
"""
Add member field to Sales Invoice doctype

Created: 2025-08-01
Purpose: Add a custom field to link Sales Invoices directly to Members
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def add_member_field_to_sales_invoice():
    """Add member field to Sales Invoice doctype"""

    print("Adding member field to Sales Invoice doctype...")

    # Define the custom field
    custom_fields = {
        "Sales Invoice": [
            {
                "fieldname": "member",
                "label": "Member",
                "fieldtype": "Link",
                "options": "Member",
                "insert_after": "customer",
                "read_only": 1,
                "fetch_from": "customer.member",
                "description": "Association member linked to this invoice",
                "in_list_view": 0,
                "in_standard_filter": 1,
            }
        ]
    }

    # Create the custom field
    create_custom_fields(custom_fields)

    print("✅ Custom field 'member' added to Sales Invoice doctype")

    # Clear cache
    frappe.clear_cache(doctype="Sales Invoice")

    return True


def populate_existing_invoices():
    """Populate member field in existing Sales Invoices"""

    print("\nPopulating member field in existing Sales Invoices...")

    # Get all Sales Invoices with customers that have member links
    invoices = frappe.db.sql(
        """
        SELECT
            si.name as invoice_name,
            si.customer,
            c.member
        FROM `tabSales Invoice` si
        INNER JOIN `tabCustomer` c ON si.customer = c.name
        WHERE c.member IS NOT NULL
        AND si.docstatus < 2
    """,
        as_dict=True,
    )

    updated_count = 0

    for invoice in invoices:
        try:
            # Update the member field directly
            frappe.db.set_value(
                "Sales Invoice", invoice.invoice_name, "member", invoice.member, update_modified=False
            )
            updated_count += 1

            if updated_count % 100 == 0:
                print(f"Updated {updated_count} invoices...")
                frappe.db.commit()

        except Exception as e:
            print(f"Error updating invoice {invoice.invoice_name}: {str(e)}")
            continue

    # Final commit
    frappe.db.commit()

    print(f"✅ Updated {updated_count} Sales Invoices with member information")

    return updated_count


def main():
    """Main function to add field and populate data"""

    # Add the custom field
    add_member_field_to_sales_invoice()

    # Populate existing invoices
    count = populate_existing_invoices()

    print(f"\n✅ Process completed. Updated {count} invoices.")


if __name__ == "__main__":
    main()
