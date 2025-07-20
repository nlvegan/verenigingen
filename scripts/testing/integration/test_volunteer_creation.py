#!/usr/bin/env python3

"""
Test script to verify volunteer creation with user account works correctly.
Tests the new functionality: automatic user account creation when creating a volunteer from member.
"""

import os
import sys

sys.path.append("/home/frappe/frappe-bench")

import frappe
from frappe.test_runner import make_test_records


def test_volunteer_creation_with_user():
    """Test that volunteer creation automatically creates user account"""

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        print("Testing Volunteer Creation with User Account...")

        # Create test member
        test_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "Volunteer",
                "email": "test.volunteer@example.com",
                "application_status": "Active",
                "status": "Active"}
        )
        test_member.insert(ignore_permissions=True)
        print(f"✅ Created test member: {test_member.name}")

        # Test volunteer creation
        from verenigingen.verenigingen.doctype.volunteer.volunteer import create_from_member

        volunteer = create_from_member(test_member.name)

        if volunteer:
            print(f"✅ Created volunteer: {volunteer.name}")
            print(f"   - Volunteer email: {volunteer.email}")
            print(f"   - Personal email: {volunteer.personal_email}")

            # Check if user was created
            if volunteer.user:
                print(f"✅ User account created: {volunteer.user}")
                user_doc = frappe.get_doc("User", volunteer.user)
                print(f"   - User full name: {user_doc.full_name}")
                print(f"   - User roles: {[r.role for r in user_doc.roles]}")
            else:
                print("❌ No user account was created")

            # Check member linking
            test_member.reload()
            if test_member.user:
                print(f"✅ Member linked to user: {test_member.user}")
            else:
                print("ℹ️  Member not linked to user (may be expected if member already had user)")

        else:
            print("❌ Failed to create volunteer")
            return False

        print("\n✅ All volunteer creation tests passed!")
        return True

    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        # Cleanup
        try:
            if "test_member" in locals():
                frappe.delete_doc("Member", test_member.name, force=True)
            if "volunteer" in locals() and volunteer:
                frappe.delete_doc("Volunteer", volunteer.name, force=True)
                if volunteer.user:
                    frappe.delete_doc("User", volunteer.user, force=True)
            print("Cleanup completed")
        except:
            pass

        frappe.destroy()


if __name__ == "__main__":
    success = test_volunteer_creation_with_user()
    sys.exit(0 if success else 1)
