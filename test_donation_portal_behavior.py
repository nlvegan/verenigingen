#!/usr/bin/env python3
"""
Test script to validate donation portal behavior before/after transaction management fixes

This tests the specific functions in manage_donations.py that have framework conflicts:
- cancel_recurring_donation (line 324: frappe.db.commit() after donation.save())
- update_recurring_donation_amount (line 419: frappe.db.commit() after donation.save())
"""

import os
import sys

import frappe
from frappe import _
from frappe.utils import now_datetime, today

# Add the app directory to Python path
app_path = "/home/frappe/frappe-bench/apps/verenigingen"
if app_path not in sys.path:
    sys.path.append(app_path)


def setup_test_environment():
    """Initialize Frappe environment for testing"""
    if not frappe.db:
        frappe.init(site="dev.veganisme.net")
        frappe.connect()

    # Set a test user context
    frappe.set_user("Administrator")


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

    return donation.name


def test_cancel_recurring_donation_current_behavior(donation_id):
    """Test current behavior of cancel_recurring_donation function"""

    print("\n=== Testing CURRENT cancel_recurring_donation behavior ===")
    print(f"Testing with donation ID: {donation_id}")

    # Import the function we're testing
    from verenigingen.templates.pages.manage_donations import cancel_recurring_donation

    # Get initial state
    initial_donation = frappe.get_doc("Donation", donation_id)
    initial_status = initial_donation.status
    initial_cancelled_date = initial_donation.recurring_cancelled_date

    print(f"Before: status={initial_status}, cancelled_date={initial_cancelled_date}")

    try:
        # Call the function
        result = cancel_recurring_donation(donation_id)

        print(f"Function result: {result}")

        # Check post-operation state
        updated_donation = frappe.get_doc("Donation", donation_id)
        final_status = updated_donation.status
        final_cancelled_date = updated_donation.recurring_cancelled_date

        print(f"After: status={final_status}, cancelled_date={final_cancelled_date}")

        # Validate the operation worked
        success = (
            result.get("status") == "success"
            and final_status == "Cancelled"
            and final_cancelled_date is not None
        )

        print(f"Operation successful: {success}")

        return success, result

    except Exception as e:
        print(f"ERROR in cancel_recurring_donation: {str(e)}")
        return False, {"error": str(e)}


def test_update_donation_amount_current_behavior(donation_id, new_amount=35.0):
    """Test current behavior of update_recurring_donation_amount function"""

    print("\n=== Testing CURRENT update_recurring_donation_amount behavior ===")
    print(f"Testing with donation ID: {donation_id}, new amount: {new_amount}")

    # First, create a fresh active donation for this test
    fresh_donation_id = create_test_donation()

    from verenigingen.templates.pages.manage_donations import update_recurring_donation_amount

    # Get initial state
    initial_donation = frappe.get_doc("Donation", fresh_donation_id)
    initial_amount = initial_donation.recurring_donation_amount

    print(f"Before: amount={initial_amount}")

    try:
        # Call the function
        result = update_recurring_donation_amount(fresh_donation_id, new_amount)

        print(f"Function result: {result}")

        # Check post-operation state
        updated_donation = frappe.get_doc("Donation", fresh_donation_id)
        final_amount = updated_donation.recurring_donation_amount

        print(f"After: amount={final_amount}")

        # Validate the operation worked
        success = result.get("status") == "success" and final_amount == new_amount

        print(f"Operation successful: {success}")

        return success, result

    except Exception as e:
        print(f"ERROR in update_recurring_donation_amount: {str(e)}")
        return False, {"error": str(e)}


def check_for_transaction_warnings():
    """Check recent logs for any implicit commit warnings"""

    print("\n=== Checking for transaction warnings ===")

    # This is a placeholder - in a real system you'd check the actual log files
    # For now, we'll just note that we should monitor the logs
    print("NOTE: Monitor /home/frappe/frappe-bench/logs/frappe.log for any 'implicit commit' warnings")

    return True


def main():
    """Run the complete behavior validation test"""

    print("=" * 60)
    print("DONATION PORTAL BEHAVIOR TEST - BEFORE TRANSACTION FIX")
    print("=" * 60)

    setup_test_environment()

    # Create test data
    donation_id = create_test_donation()
    print(f"Created test donation: {donation_id}")

    # Test current behavior
    cancel_success, _cancel_result = test_cancel_recurring_donation_current_behavior(donation_id)
    update_success, _update_result = test_update_donation_amount_current_behavior(donation_id)

    # Check for warnings
    check_for_transaction_warnings()

    # Summary
    print("\n=== TEST SUMMARY ===")
    print(f"Cancel donation function: {'PASS' if cancel_success else 'FAIL'}")
    print(f"Update donation amount function: {'PASS' if update_success else 'FAIL'}")
    print(
        f"Overall portal behavior: {'WORKING' if (cancel_success and update_success) else 'ISSUES DETECTED'}"
    )

    print("\n=== NEXT STEPS ===")
    print("1. Run this test to establish baseline behavior")
    print("2. Remove frappe.db.commit() calls from manage_donations.py")
    print("3. Run this test again to validate no regression")
    print("4. Monitor production logs for any new transaction warnings")


if __name__ == "__main__":
    main()
