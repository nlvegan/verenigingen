"""
Patch to add Customer.member custom field for direct linking
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    """Add custom field to link Customer directly to Member"""

    # Define the custom field
    custom_fields = {
        "Customer": [
            {
                "fieldname": "member",
                "label": "Member",
                "fieldtype": "Link",
                "options": "Member",
                "insert_after": "customer_name",
                "description": "Direct link to the associated Member record",
                "in_list_view": 1,
                "in_standard_filter": 1,
                "in_global_search": 1,
                "in_preview": 1,
                "show_dashboard": 1,
                "search_index": 1,
                "unique": 1,
            }
        ]
    }

    # Create the custom field
    create_custom_fields(custom_fields, update=True)

    print("✅ Added Customer.member custom field")

    # Now update existing customers that have members
    update_existing_customer_member_links()


def update_existing_customer_member_links():
    """Update existing customers to populate the member field"""

    # Find all members with customers
    members_with_customers = frappe.db.sql(
        """
        SELECT name, customer, full_name
        FROM `tabMember`
        WHERE customer IS NOT NULL AND customer != ''
    """,
        as_dict=True,
    )

    updated_count = 0

    for member in members_with_customers:
        try:
            # Check if customer exists
            if frappe.db.exists("Customer", member.customer):
                # Update customer with member link
                frappe.db.set_value("Customer", member.customer, "member", member.name)
                updated_count += 1
                print(f"✅ Linked Customer {member.customer} to Member {member.name} ({member.full_name})")
            else:
                print(f"⚠️ Customer {member.customer} not found for Member {member.name}")
        except Exception as e:
            print(f"❌ Error linking Customer {member.customer} to Member {member.name}: {e}")

    frappe.db.commit()
    print(f"✅ Updated {updated_count} customer-member links")
