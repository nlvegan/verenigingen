"""
Simple validation test
"""

import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_basic_validation():
    """Simple test of the validation fixes"""
    try:
        # Test that we can create a dues schedule with dues_rate field
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = "Test-Basic"
        schedule.is_template = 1
        schedule.membership_type = "Standard"  # Assume this exists
        schedule.billing_frequency = "Monthly"
        schedule.status = "Active"
        schedule.dues_rate = 25.0

        # Test validation
        schedule.validate()

        return {
            "status": "success",
            "dues_rate": schedule.dues_rate,
            "field_exists": hasattr(schedule, "dues_rate"),
            "validation_passed": True,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "field_exists": hasattr(schedule, "dues_rate") if "schedule" in locals() else False,
        }
