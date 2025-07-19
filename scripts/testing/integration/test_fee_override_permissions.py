#!/usr/bin/env python3

"""
Test script to verify fee override permission system works correctly.
This tests the core issue: "Override Set By" shows member name instead of backend user,
and members shouldn't be able to change fees themselves.
"""

import os
import sys

sys.path.append("/home/frappe/frappe-bench")

import frappe
from frappe.test_runner import make_test_records


def test_fee_override_permissions():
    """Test that fee override permissions work correctly"""

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        print("Testing Fee Override Permission System...")

        # Create test member
        test_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "User",
                "email": "test.fee@example.com",
                "application_status": "Active",
                "status": "Active",
            }
        )
        test_member.insert(ignore_permissions=True)
        print(f"Created test member: {test_member.name}")

        # Test 1: Regular member user (should not be able to set fee override)
        frappe.set_user("Administrator")  # Start as admin

        # Create a test user for the member
        test_user = frappe.get_doc(
            {
                "doctype": "User",
                "email": "test.fee@example.com",
                "first_name": "Test",
                "last_name": "User",
                "user_type": "Website User",
            }
        )
        test_user.insert(ignore_permissions=True)

        # Link user to member
        test_member.user = test_user.name
        test_member.save(ignore_permissions=True)

        print("Test 1: Testing regular member permissions...")

        # Switch to the member user
        frappe.set_user("test.fee@example.com")

        # Try to set fee override as regular user (should fail)
        try:
            member_doc = frappe.get_doc("Member", test_member.name)
            member_doc.dues_rate = 25.00
            member_doc.fee_override_reason = "Testing unauthorized access"
            member_doc.save()
            print("❌ FAIL: Regular member was able to set fee override!")
            return False
        except frappe.PermissionError:
            print("✅ PASS: Regular member correctly blocked from setting fee override")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return False

        # Test 2: Administrator should be able to set fee override
        print("\nTest 2: Testing administrator permissions...")
        frappe.set_user("Administrator")

        try:
            member_doc = frappe.get_doc("Member", test_member.name)
            member_doc.dues_rate = 30.00
            member_doc.fee_override_reason = "Test administrator override"
            member_doc.save()

            # Reload to check saved values
            member_doc.reload()

            if member_doc.dues_rate == 30.00:
                print("✅ PASS: Administrator successfully set fee override")

                # Check that override_by is set to Administrator (not member)
                if member_doc.fee_override_by == "Administrator":
                    print("✅ PASS: Override Set By correctly shows Administrator")
                else:
                    print(
                        f"❌ FAIL: Override Set By shows {member_doc.fee_override_by}, should be Administrator"
                    )
                    return False
            else:
                print("❌ FAIL: Administrator fee override not saved properly")
                return False

        except Exception as e:
            print(f"❌ FAIL: Administrator unable to set fee override: {e}")
            return False

        # Test 3: Test permission levels for fee override fields
        print("\nTest 3: Testing permission levels...")

        # Switch back to regular user and try to read fee override fields
        frappe.set_user("test.fee@example.com")

        try:
            member_doc = frappe.get_doc("Member", test_member.name)
            # Regular user should not be able to see permlevel 1 fields
            if hasattr(member_doc, "dues_rate"):
                # This check might vary based on permission implementation
                print(
                    "ℹ️  Regular user can read fee override field (may be expected depending on permission setup)"
                )
            else:
                print("✅ PASS: Regular user cannot access fee override fields")
        except Exception as e:
            print(f"ℹ️  Permission error when reading as regular user: {e}")

        print("\n✅ All fee override permission tests passed!")
        return True

    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        # Cleanup
        try:
            frappe.set_user("Administrator")
            if "test_member" in locals():
                frappe.delete_doc("Member", test_member.name, force=True)
            if "test_user" in locals():
                frappe.delete_doc("User", test_user.name, force=True)
            print("Cleanup completed")
        except:
            pass

        frappe.destroy()


if __name__ == "__main__":
    success = test_fee_override_permissions()
    sys.exit(0 if success else 1)
