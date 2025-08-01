#!/usr/bin/env python3
"""
Test the real application flow with dues rate preservation

Created: 2025-08-01
Purpose: Test actual membership application approval with user-selected dues rate
TODO: Remove after verification complete
"""

import frappe
from frappe.utils import today


def test_real_application_flow():
    """Test the complete application → approval flow"""

    print("Testing Real Application Flow")
    print("=" * 40)

    # Create a test member with application data (simulating what the application form does)
    test_member = frappe.new_doc("Member")
    test_member.first_name = "TestUser"
    test_member.last_name = "DuesRateTest"
    test_member.email = "test.duesrate@example.com"
    test_member.address_line1 = "Test Street 123"
    test_member.postal_code = "1234AB"
    test_member.city = "Test City"
    test_member.country = "Netherlands"

    # Application-specific fields
    test_member.status = "Pending"
    test_member.application_status = "Pending"
    test_member.application_date = today()
    test_member.membership_type = "Daglid"  # Use existing membership type
    test_member.dues_rate = 6.0  # User selected €6.00 during application
    test_member.contribution_amount = 6.0  # Also set this field
    test_member.selected_membership_type = "Daglid"
    test_member.fee_override_reason = (
        "User selected this amount during membership application"  # Required for validation
    )

    print(f"Creating test member with dues_rate = €{test_member.dues_rate:.2f}")

    try:
        test_member.insert(ignore_permissions=True)
        print(f"✅ Test member created: {test_member.name}")

        # Check the template configuration
        membership_type_doc = frappe.get_doc("Membership Type", "Daglid")
        if membership_type_doc.dues_schedule_template:
            template = frappe.get_doc("Membership Dues Schedule", membership_type_doc.dues_schedule_template)
            print(f"Template dues_rate: €{template.dues_rate:.2f}")
            print(f"Template minimum_amount: €{template.minimum_amount:.2f}")
            print(f"Template suggested_amount: €{template.suggested_amount:.2f}")

        # Now test creating a dues schedule from template
        print("\nTesting dues schedule creation...")

        # This is what happens during membership approval
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            MembershipDuesSchedule,
        )

        # Check if member already has a schedule (cleanup from previous tests)
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": test_member.name, "is_template": 0}
        )
        if existing_schedule:
            print(f"Cleaning up existing schedule: {existing_schedule}")
            frappe.delete_doc("Membership Dues Schedule", existing_schedule, force=True)

        # Create dues schedule from template (this calls our new logic)
        schedule_name = MembershipDuesSchedule.create_from_template(
            member_name=test_member.name, membership_type="Daglid"
        )

        print(f"✅ Dues schedule created: {schedule_name}")

        # Verify the results
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        print(f"\n📊 Results:")
        print(f"Schedule dues_rate: €{schedule.dues_rate:.2f}")
        print(f"Schedule contribution_mode: {schedule.contribution_mode}")
        print(f"Schedule uses_custom_amount: {schedule.uses_custom_amount}")
        print(f"Schedule custom_amount_reason: {getattr(schedule, 'custom_amount_reason', 'None')}")

        # Verify user's selection was preserved
        if schedule.dues_rate == 6.0:
            print("✅ SUCCESS: User's selected dues rate (€6.00) was preserved!")
        else:
            print(f"❌ FAILURE: Expected €6.00, got €{schedule.dues_rate:.2f}")

        # Cleanup
        frappe.delete_doc("Membership Dues Schedule", schedule_name, force=True)
        frappe.delete_doc("Member", test_member.name, force=True)
        print(f"\n🧹 Cleanup completed")

    except Exception as e:
        print(f"❌ Error during test: {str(e)}")
        # Cleanup on error
        try:
            if test_member.name:
                frappe.delete_doc("Member", test_member.name, force=True)
        except:
            pass
        raise e

    print("\n" + "=" * 40)
    print("Real application flow test completed")


if __name__ == "__main__":
    test_real_application_flow()
