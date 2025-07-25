#!/usr/bin/env python3

"""
Debug script to test validation methods directly
"""

import frappe
from frappe.utils import today


def debug_validation():
    """Debug the validation methods to see what's happening"""

    # Connect to the site
    frappe.init("dev.veganisme.net")
    frappe.connect()

    print("=== Debugging Validation Methods ===")

    # Try to create a simple dues schedule
    schedule = frappe.new_doc("Membership Dues Schedule")
    schedule.schedule_name = "Debug-Test-Schedule"
    schedule.membership_type = "Individual"  # Assuming this exists
    schedule.dues_rate = 0.0  # Should fail validation
    schedule.billing_frequency = "Monthly"
    schedule.status = "Active"
    schedule.auto_generate = 1
    schedule.next_invoice_date = today()
    schedule.is_template = 1  # Template doesn't need member

    print(f"Created schedule with dues_rate: {schedule.dues_rate}")

    # Test rate validation
    try:
        print("\n--- Testing validate_dues_rate() ---")
        rate_result = schedule.validate_dues_rate()
        print(f"Rate validation result: {rate_result}")
    except Exception as e:
        print(f"Exception in rate validation: {e}")
        import traceback

        traceback.print_exc()

    # Try with negative rate
    schedule.dues_rate = -10.0
    print(f"\nChanged dues_rate to: {schedule.dues_rate}")

    try:
        rate_result = schedule.validate_dues_rate()
        print(f"Negative rate validation result: {rate_result}")
    except Exception as e:
        print(f"Exception in negative rate validation: {e}")
        import traceback

        traceback.print_exc()

    # Test positive rate
    schedule.dues_rate = 25.0
    print(f"\nChanged dues_rate to: {schedule.dues_rate}")

    try:
        rate_result = schedule.validate_dues_rate()
        print(f"Positive rate validation result: {rate_result}")
    except Exception as e:
        print(f"Exception in positive rate validation: {e}")
        import traceback

        traceback.print_exc()

    print("\n=== Debug Complete ===")


if __name__ == "__main__":
    debug_validation()
