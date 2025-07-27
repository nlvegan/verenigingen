"""
Debug validation methods for testing
"""

import frappe
from frappe.utils import today


@frappe.whitelist()
def debug_factory_method():
    """Debug the factory method to see what schedule it creates"""

    print("=== Debugging Factory Method ===")

    # Import the test data factory
    from verenigingen.tests.test_data_factory import TestDataFactory
    from verenigingen.tests.utils.base import VereningingenTestCase

    # Create factory
    factory = TestDataFactory()

    # Try to create a member and membership first
    member = factory.create_test_members(1)[0]
    print(f"Created member: {member.name}")

    # Create membership type
    membership_type = factory.create_test_membership_types(1)[0]
    print(f"Created membership type: {membership_type.name}")

    # Create membership
    membership = frappe.new_doc("Membership")
    membership.member = member.name
    membership.membership_type = membership_type.name
    membership.start_date = today()
    membership.status = "Active"
    membership.save()
    membership.submit()
    print(f"Created and submitted membership: {membership.name}")

    # Try to create dues schedule using factory method
    try:
        schedule = factory.create_dues_schedule_for_member(member.name, membership_type.name)
        print(f"Factory created schedule: {schedule.name}")
        print(f"Schedule dues_rate: {schedule.dues_rate}")
        print(f"Schedule membership_type: {schedule.membership_type}")

        # Test validation on this schedule
        rate_result = schedule.validate_dues_rate()
        print(f"Validation result: {rate_result}")

        return {
            "schedule_name": schedule.name,
            "dues_rate": schedule.dues_rate,
            "validation_result": rate_result,
        }

    except Exception as e:
        print(f"Exception in factory method: {e}")
        import traceback

        traceback.print_exc()
        return {"error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def debug_validation_methods():
    """Debug the validation methods to see what's happening"""

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
        return rate_result
    except Exception as e:
        print(f"Exception in rate validation: {e}")
        import traceback

        traceback.print_exc()
        return {"error": str(e), "traceback": traceback.format_exc()}
