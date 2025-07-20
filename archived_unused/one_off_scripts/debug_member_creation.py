#!/usr/bin/env python3
"""Debug script to test member creation"""

import frappe
from frappe.utils import today


def debug_member_creation():
    """Debug member creation to understand the dues_rate issue"""
    try:
        # Create a new member document
        member = frappe.new_doc("Member")

        # Set basic fields
        member.first_name = "Test"
        member.last_name = "Member"
        member.email = f"test.{frappe.generate_hash(length=6)}@example.com"
        member.member_since = today()
        member.address_line1 = "123 Test Street"
        member.postal_code = "1234AB"
        member.city = "Test City"
        member.country = "Netherlands"
        member.status = "Active"

        # Check if dues_rate field exists
        print("Member fields available:")
        for field in member.meta.get_valid_columns():
            print(f"  - {field}")

        # Check if dues_rate is in the member object
        print(f"\nMember has dues_rate attr: {hasattr(member, 'dues_rate')}")
        print(f"Member dues_rate value: {getattr(member, 'dues_rate', 'NOT FOUND')}")

        # Try to save without dues_rate
        print("\nTrying to save member...")
        member.save()
        print(f"Member saved successfully: {member.name}")

        # Clean up
        member.delete()
        print("Member deleted successfully")

    except Exception as e:
        print(f"Error: {e}")
        print(f"Error type: {type(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    debug_member_creation()
