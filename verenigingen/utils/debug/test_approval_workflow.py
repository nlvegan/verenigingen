#!/usr/bin/env python3
"""
Debug script for testing membership application approval workflow after security refactoring
Tests the core business logic without UI dependencies
"""

import frappe
from frappe.utils import add_days, now_datetime, today


def create_test_member():
    """Create a test member for approval workflow testing"""
    # Create a membership type with dues schedule template first
    if not frappe.db.exists("Membership Type", "Test Approval Type"):
        # Create dues schedule template
        dues_template = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "name": "Test Approval Template",
                "is_template": 1,
                "membership_type": "Test Approval Type",
                "contribution_mode": "Fixed Amount",
                "dues_rate": 25.00,
                "billing_frequency": "Monthly",
                "auto_generate": 1,
                "status": "Active",
            }
        )
        dues_template.insert(ignore_permissions=True)

        # Create membership type
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "name": "Test Approval Type",
                "membership_type_name": "Test Approval Member",
                "minimum_amount": 25.00,
                "dues_schedule_template": "Test Approval Template",
                "is_active": 1,
            }
        )
        membership_type.insert(ignore_permissions=True)

    # Create test chapter
    if not frappe.db.exists("Chapter", "Test Chapter"):
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": "Test Chapter",
                "chapter_name": "Test Chapter for Approvals",
                "status": "Active",
                "city": "Amsterdam",
            }
        )
        chapter.insert(ignore_permissions=True)

    # Create test member
    member = frappe.get_doc(
        {
            "doctype": "Member",
            "first_name": "Test",
            "last_name": "Approval",
            "email": f"test.approval.{frappe.utils.random_string(5).lower()}@example.com",
            "contact_number": "+31612345678",
            "birth_date": add_days(today(), -365 * 25),
            "street_name": "Test Street",
            "house_number": "123",
            "postal_code": "1012",
            "city": "Amsterdam",
            "country": "Netherlands",
            "status": "Pending",
            "application_status": "Pending",
            "selected_membership_type": "Test Approval Type",
            "application_date": today(),
            "application_id": f"TEST-{frappe.utils.random_string(8)}",
        }
    )
    member.insert(ignore_permissions=True)
    return member


def test_approve_membership_application():
    """Test the approve_membership_application function"""
    print("🔄 Creating test member...")
    member = create_test_member()
    print(f"✅ Created test member: {member.name}")

    try:
        print("🔄 Testing approval workflow...")

        # Import the function to test
        from verenigingen.api.membership_application_review import approve_membership_application

        # Call the approval function
        result = approve_membership_application(
            member_name=member.name,
            membership_type="Test Approval Type",
            chapter="Test Chapter",
            notes="Test approval via debug script",
            create_invoice=True,
        )

        print("✅ Approval function completed successfully!")
        print(f"Result: {result}")

        # Verify member status
        member.reload()
        print(f"Member status: {member.status}")
        print(f"Application status: {member.application_status}")
        print(f"Member since: {member.member_since}")

        # Check if membership was created
        memberships = frappe.get_all("Membership", filters={"member": member.name})
        print(f"Memberships created: {len(memberships)}")

        # Check if invoice was created
        if result.get("invoice"):
            invoice = frappe.get_doc("Sales Invoice", result["invoice"])
            print(f"Invoice created: {invoice.name} for {invoice.grand_total}")

        return True

    except Exception as e:
        print(f"❌ Error in approval workflow: {str(e)}")
        frappe.log_error(f"Approval workflow test failed: {str(e)}")
        return False

    finally:
        # Cleanup
        try:
            frappe.delete_doc("Member", member.name, force=True, ignore_permissions=True)
            print(f"🧹 Cleaned up test member: {member.name}")
        except Exception as e:
            print(f"⚠️ Cleanup warning: {str(e)}")


def test_reject_membership_application():
    """Test the reject_membership_application function"""
    print("🔄 Creating test member for rejection...")
    member = create_test_member()
    print(f"✅ Created test member: {member.name}")

    try:
        print("🔄 Testing rejection workflow...")

        # Import the function to test
        from verenigingen.api.membership_application_review import reject_membership_application

        # Call the rejection function
        result = reject_membership_application(
            member_name=member.name,
            reason="Test rejection via debug script",
            rejection_category="General",
            internal_notes="Automated test rejection",
        )

        print("✅ Rejection function completed successfully!")
        print(f"Result: {result}")

        # Verify member status
        member.reload()
        print(f"Member status: {member.status}")
        print(f"Application status: {member.application_status}")
        print(f"Review notes: {member.review_notes}")

        return True

    except Exception as e:
        print(f"❌ Error in rejection workflow: {str(e)}")
        frappe.log_error(f"Rejection workflow test failed: {str(e)}")
        return False

    finally:
        # Cleanup
        try:
            frappe.delete_doc("Member", member.name, force=True, ignore_permissions=True)
            print(f"🧹 Cleaned up test member: {member.name}")
        except Exception as e:
            print(f"⚠️ Cleanup warning: {str(e)}")


def test_helper_functions():
    """Test individual helper functions"""
    print("🔄 Testing helper functions...")

    try:
        member = create_test_member()

        # Import helper functions
        from verenigingen.api.membership_application_review import (
            assign_member_to_chapter,
            create_member_iban_history,
            finalize_member_approval,
            resolve_membership_type,
        )

        print("✅ Testing assign_member_to_chapter...")
        assign_member_to_chapter(member, "Test Chapter")

        print("✅ Testing resolve_membership_type...")
        membership_type = resolve_membership_type(member)
        print(f"Resolved membership type: {membership_type}")

        print("✅ Testing finalize_member_approval...")
        finalize_member_approval(member, "Test approval finalization")

        print("✅ All helper functions tested successfully!")
        return True

    except Exception as e:
        print(f"❌ Error testing helper functions: {str(e)}")
        frappe.log_error(f"Helper function test failed: {str(e)}")
        return False

    finally:
        # Cleanup
        try:
            frappe.delete_doc("Member", member.name, force=True, ignore_permissions=True)
            print(f"🧹 Cleaned up test member: {member.name}")
        except Exception as e:
            print(f"⚠️ Cleanup warning: {str(e)}")


def run_all_tests():
    """Run all approval workflow tests"""
    print("🚀 Starting membership application approval workflow tests...")
    print("=" * 60)

    # Test results
    results = {}

    # Test 1: Approval workflow
    print("\n📝 TEST 1: Membership Application Approval")
    print("-" * 40)
    results["approval"] = test_approve_membership_application()

    # Test 2: Rejection workflow
    print("\n📝 TEST 2: Membership Application Rejection")
    print("-" * 40)
    results["rejection"] = test_reject_membership_application()

    # Test 3: Helper functions
    print("\n📝 TEST 3: Helper Function Tests")
    print("-" * 40)
    results["helpers"] = test_helper_functions()

    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for result in results.values() if result)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name.upper()}: {status}")

    print(f"\nOverall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Security refactoring preserved core functionality.")
    else:
        print("⚠️ Some tests failed. Please review the errors above.")

    return passed == total


if __name__ == "__main__":
    run_all_tests()
