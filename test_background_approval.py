#!/usr/bin/env python3
"""
Test script for the new background approval system.

This script creates a test member and runs the background approval process
to verify that the system works correctly.
"""

import frappe


def test_background_approval():
    """Test the background approval system with a real member."""
    print("Testing background approval system...")

    # Connect to Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        # Set user for testing
        frappe.set_user("Administrator")

        # Create a test member
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        factory = EnhancedTestCase()

        print("Creating test member...")
        member = factory.create_test_member(
            first_name="Background", last_name="Test", email="bgtest@example.com", birth_date="1990-01-01"
        )

        # Set application status to pending
        member.application_status = "Pending"
        member.status = "Pending"
        member.save()

        print(f"Test member created: {member.name}")

        # Test the background approval API
        print("Testing background approval API...")

        from verenigingen.api.background_approval_api import approve_membership_application_background

        result = approve_membership_application_background(
            member_name=member.name,
            membership_type="Monthly Membership",  # Assuming this exists
            chapter=None,
            notes="Test approval via background system",
            create_invoice=True,
        )

        print("Approval result:")
        print(f"  Success: {result.get('success')}")
        print(f"  Message: {result.get('message')}")
        print(f"  Member ID: {result.get('member_id')}")
        print(f"  Invoice: {result.get('invoice')}")
        print(f"  Background operations: {result.get('background_processing', {}).get('operations')}")

        # Check member status after approval
        member.reload()
        print(f"\nMember status after approval:")
        print(f"  Application Status: {member.application_status}")
        print(f"  Status: {member.status}")
        print(f"  Member ID: {member.member_id}")

        # Test progress tracking
        print("\nTesting progress tracking...")
        from verenigingen.api.background_approval_api import get_approval_progress

        progress = get_approval_progress(member.name)
        print(f"Progress result: {progress}")

        print("\n✅ Background approval test completed successfully!")

    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        import traceback

        traceback.print_exc()

    finally:
        frappe.destroy()


if __name__ == "__main__":
    test_background_approval()
