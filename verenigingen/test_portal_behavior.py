#!/usr/bin/env python3
"""
Simple test functions for donation portal behavior validation
"""

import frappe
from frappe.utils import now_datetime, today


def create_test_donation():
    """Create a test donation for portal testing"""

    # Create test member if needed
    test_member_name = "Test-Member-Portal-001"
    if not frappe.db.exists("Member", test_member_name):
        member = frappe.new_doc("Member")
        member.first_name = "Test"
        member.last_name = "Portal User"
        member.email_address = f"test-portal-{now_datetime().strftime('%H%M%S')}@example.com"
        member.birth_date = "1990-01-01"
        member.insert()
        test_member_name = member.name

    # Create test donation
    donation = frappe.new_doc("Donation")
    donation.update(
        {
            "donor": test_member_name,
            "donation_type": "Recurring",
            "recurring_donation_amount": 25.0,
            "currency": "EUR",
            "recurring_frequency": "1 month",
            "start_date": today(),
            "status": "Active",
            "enable_recurring_donation": 1,
        }
    )

    donation.insert()
    donation.submit()

    print(f"Created test donation: {donation.name}")
    return donation.name


def test_cancel_recurring_donation(donation_id):
    """Test the cancel_recurring_donation function"""

    from verenigingen.templates.pages.manage_donations import cancel_recurring_donation

    print(f"Testing cancel_recurring_donation with ID: {donation_id}")

    # Get initial state
    initial_donation = frappe.get_doc("Donation", donation_id)
    initial_status = initial_donation.status

    print(f"Before: status={initial_status}")

    try:
        result = cancel_recurring_donation(donation_id)

        # Check post-operation state
        updated_donation = frappe.get_doc("Donation", donation_id)
        final_status = updated_donation.status

        print(f"After: status={final_status}")
        print(f"Result: {result}")

        success = result.get("status") == "success" and final_status == "Cancelled"
        print(f"Test result: {'PASS' if success else 'FAIL'}")

        return success

    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False


def test_update_donation_amount():
    """Test the update_recurring_donation_amount function"""

    # Create fresh donation for this test
    donation_id = create_test_donation()

    from verenigingen.templates.pages.manage_donations import update_recurring_donation_amount

    print(f"Testing update_recurring_donation_amount with ID: {donation_id}")

    # Get initial state
    initial_donation = frappe.get_doc("Donation", donation_id)
    initial_amount = initial_donation.recurring_donation_amount
    new_amount = 35.0

    print(f"Before: amount={initial_amount}")

    try:
        result = update_recurring_donation_amount(donation_id, new_amount)

        # Check post-operation state
        updated_donation = frappe.get_doc("Donation", donation_id)
        final_amount = updated_donation.recurring_donation_amount

        print(f"After: amount={final_amount}")
        print(f"Result: {result}")

        success = result.get("status") == "success" and final_amount == new_amount
        print(f"Test result: {'PASS' if success else 'FAIL'}")

        return success

    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False


def run_baseline_tests():
    """Run complete baseline test suite"""

    print("=" * 60)
    print("DONATION PORTAL BASELINE TEST - BEFORE TRANSACTION FIX")
    print("=" * 60)

    # Create test donation
    donation_id = create_test_donation()

    # Run tests
    cancel_result = test_cancel_recurring_donation(donation_id)
    update_result = test_update_donation_amount()

    print(f"\n=== BASELINE TEST SUMMARY ===")
    print(f"Cancel donation: {'PASS' if cancel_result else 'FAIL'}")
    print(f"Update donation amount: {'PASS' if update_result else 'FAIL'}")
    print(f"Overall: {'BASELINE ESTABLISHED' if (cancel_result and update_result) else 'ISSUES DETECTED'}")

    return cancel_result and update_result
