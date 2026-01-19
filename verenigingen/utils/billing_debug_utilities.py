# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Billing Debug Utilities - Development and debugging functions for dues schedules.

This module contains development-only utilities for testing and debugging
the billing system. These functions should NOT be used in production.

Functions:
- test_billing_day_field: Test billing_day field implementation
- create_test_schedule: Create a test dues schedule for development
- debug_template_daglid_issue: Debug template billing frequency issues
- test_template_daglid_fix: Test template preservation during recreation
- validate_and_fix_schedule_dates: Validate and fix schedule dates

These were extracted from membership_dues_schedule.py to reduce
controller size and keep debug code separate from production code.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.utils.member_utils import get_active_membership_for_member
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    development_only_api,
)


@development_only_api(operation_type=OperationType.UTILITY)
def test_billing_day_field():
    """
    Test billing_day field implementation.

    Creates test members with and without member_since dates,
    then verifies the billing_day is set correctly on their schedules.

    Returns:
        dict: Test results with success/failure status
    """
    try:
        # Test 1: Create a member with member_since date
        test_member = frappe.new_doc("Member")
        test_member.first_name = "Billing"
        test_member.last_name = "Test"
        test_member.email = f"billing.test.{frappe.generate_hash(length=6)}@example.com"
        test_member.member_since = "2023-03-15"  # 15th of the month
        test_member.save()

        # Test 2: Create a dues schedule for this member
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Billing-Day-{frappe.generate_hash(length=4)}"
        schedule.is_template = 0
        schedule.member = test_member.name
        schedule.membership_type = "Test Membership"
        schedule.dues_rate = 10.0
        schedule.save()

        # Test 3: Create a member without member_since date
        no_date_member = frappe.new_doc("Member")
        no_date_member.first_name = "NoDate"
        no_date_member.last_name = "Test"
        no_date_member.email = f"nodate.test.{frappe.generate_hash(length=6)}@example.com"
        no_date_member.member_since = None
        no_date_member.save()

        # Test 4: Create a dues schedule for member without date
        no_date_schedule = frappe.new_doc("Membership Dues Schedule")
        no_date_schedule.schedule_name = f"Test-No-Date-{frappe.generate_hash(length=4)}"
        no_date_schedule.is_template = 0
        no_date_schedule.member = no_date_member.name
        no_date_schedule.membership_type = "Test Membership"
        no_date_schedule.dues_rate = 10.0
        no_date_schedule.save()

        results = {
            "test_1_member_with_date": {
                "member_since": test_member.member_since,
                "expected_billing_day": 15,
                "actual_billing_day": schedule.billing_day,
                "correct": schedule.billing_day == 15,
            },
            "test_2_member_without_date": {
                "member_since": no_date_member.member_since,
                "expected_billing_day": 1,
                "actual_billing_day": no_date_schedule.billing_day,
                "correct": no_date_schedule.billing_day == 1,
            },
            "field_exists": hasattr(schedule, "billing_day"),
            "overall_success": schedule.billing_day == 15 and no_date_schedule.billing_day == 1,
        }

        # Cleanup
        schedule.delete()
        no_date_schedule.delete()
        test_member.delete()
        no_date_member.delete()

        return results

    except Exception as e:
        return {"error": str(e), "success": False}


@development_only_api(operation_type=OperationType.UTILITY)
def create_test_schedule(member_name, membership_name=None):
    """
    Create a test dues schedule for development.

    Tries to create from template first, falls back to manual creation.

    Args:
        member_name: Name of the member to create schedule for
        membership_name: Optional membership name

    Returns:
        str: Name of the created schedule
    """
    from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
        MembershipDuesSchedule,
    )

    try:
        return MembershipDuesSchedule.create_from_template(member_name)
    except Exception:
        # Fallback to manual creation if no template exists
        if not membership_name:
            membership_info = get_active_membership_for_member(member_name, ["name"])
            membership_name = membership_info["name"] if membership_info else None

        if not membership_name:
            frappe.throw(f"No membership found for member {member_name}")

        # Create test schedule
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.is_template = 0
        schedule.member = member_name
        schedule.schedule_name = f"Test-Schedule-{member_name}"
        schedule.billing_frequency = "Monthly"
        schedule.dues_rate = 10.00
        schedule.next_invoice_date = today()
        schedule.invoice_days_before = 0
        schedule.test_mode = 1
        schedule.auto_generate = 1
        schedule.status = "Test"
        schedule.insert()

        return schedule.name


@development_only_api(operation_type=OperationType.UTILITY)
def debug_template_daglid_issue():
    """
    Debug Template-Daglid billing frequency override issue.

    Checks the current state of the Daglid template and membership type,
    and tests the inheritance logic.

    Returns:
        dict: Debug information about template and inheritance
    """
    result = {
        "timestamp": frappe.utils.now(),
        "template_status": {},
        "membership_type_status": {},
        "inheritance_tests": {},
        "recent_schedules": [],
    }

    # Check Template-Daglid current state
    try:
        template = frappe.get_doc("Membership Dues Schedule", "Template-Daglid")
        result["template_status"] = {
            "billing_frequency": template.billing_frequency,
            "is_template": template.is_template,
            "modified": str(template.modified),
            "modified_by": template.modified_by,
        }
    except Exception as e:
        result["template_status"]["error"] = str(e)

    # Check Daglid membership type
    membership_type = None
    try:
        membership_type = frappe.get_doc("Membership Type", "Daglid")
        result["membership_type_status"] = {
            "dues_schedule_template": membership_type.dues_schedule_template,
            "amount": getattr(membership_type, "amount", 0),
        }
    except Exception as e:
        result["membership_type_status"]["error"] = str(e)

    # Test the auto-creator inheritance logic
    try:
        billing_frequency = "Annual"  # Default from auto_creator
        if membership_type and membership_type.dues_schedule_template:
            template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
            if template.billing_frequency:
                billing_frequency = template.billing_frequency
            else:
                billing_frequency = "Annual"
                frappe.log_error(
                    f"Template '{membership_type.dues_schedule_template}' has no billing_frequency configured",
                    "Membership Dues Schedule Template Configuration",
                )

            result["inheritance_tests"]["auto_creator_logic"] = {
                "would_set": billing_frequency,
                "template_value": template.billing_frequency,
                "template_truthy": bool(template.billing_frequency),
            }
    except Exception as e:
        result["inheritance_tests"]["auto_creator_error"] = str(e)

    # Test the get_template_values() method
    try:
        test_schedule = frappe.new_doc("Membership Dues Schedule")
        test_schedule.membership_type = "Daglid"
        template_values = test_schedule.get_template_values()
        result["inheritance_tests"]["get_template_values"] = {
            "billing_frequency": template_values.get("billing_frequency"),
            "all_values": template_values,
        }
    except Exception as e:
        result["inheritance_tests"]["get_template_values_error"] = str(e)

    # Check recent dues schedules
    try:
        recent_schedules = frappe.db.sql(
            """
            SELECT name, billing_frequency, modified, membership_type
            FROM `tabMembership Dues Schedule`
            WHERE membership_type = 'Daglid'
            ORDER BY modified DESC
            LIMIT 5
            """,
            as_dict=True,
        )
        result["recent_schedules"] = recent_schedules
    except Exception as e:
        result["recent_schedules_error"] = str(e)

    return result


@development_only_api(operation_type=OperationType.UTILITY)
def test_template_daglid_fix():
    """
    Test that Template-Daglid billing frequency is preserved during template recreation.

    Returns:
        dict: Test results showing before/after state
    """
    # Step 1: Check current Template-Daglid status
    before = frappe.get_doc("Membership Dues Schedule", "Template-Daglid")
    before_frequency = before.billing_frequency
    before_modified = str(before.modified)

    # Step 2: Simulate template recreation
    daglid_membership_type = frappe.get_doc("Membership Type", "Daglid")
    template_name = daglid_membership_type.create_dues_schedule_template()

    # Step 3: Check Template-Daglid status after recreation
    after = frappe.get_doc("Membership Dues Schedule", "Template-Daglid")
    after_frequency = after.billing_frequency
    after_modified = str(after.modified)

    return {
        "template_name": template_name,
        "before": {"billing_frequency": before_frequency, "modified": before_modified},
        "after": {"billing_frequency": after_frequency, "modified": after_modified},
        "preserved": before_frequency == after_frequency,
        "test_result": "PASS" if before_frequency == after_frequency else "FAIL",
    }


@critical_api(operation_type=OperationType.ADMIN)
def validate_and_fix_schedule_dates():
    """
    Validate and fix all dues schedule dates.

    Checks for unreasonably far future dates or very old dates
    and corrects them to today.

    Returns:
        dict: Report of issues found and fixed
    """
    today_date = getdate(today())
    results = {
        "total_schedules": 0,
        "issues_found": 0,
        "fixes_applied": 0,
        "issues": [],
        "success": True,
    }

    try:
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "is_template": 0},
            fields=[
                "name",
                "member",
                "billing_frequency",
                "next_invoice_date",
                "last_invoice_date",
                "modified",
            ],
        )

        results["total_schedules"] = len(schedules)

        for schedule_data in schedules:
            issues = []
            fixes = []

            try:
                schedule = frappe.get_doc("Membership Dues Schedule", schedule_data.name)

                if schedule.next_invoice_date:
                    next_date = getdate(schedule.next_invoice_date)

                    # Calculate max future days based on frequency
                    max_future_days = _get_max_future_days(schedule.billing_frequency)
                    max_future_date = add_days(today_date, max_future_days)

                    if next_date > max_future_date:
                        issues.append(f"Next invoice date too far in future: {next_date}")
                        schedule.next_invoice_date = today_date
                        fixes.append(f"Corrected next_invoice_date from {next_date} to {today_date}")

                    # Check for very old dates (6 months ago)
                    min_past_date = add_days(today_date, -180)
                    if next_date < min_past_date:
                        issues.append(f"Next invoice date too far in past: {next_date}")
                        schedule.next_invoice_date = today_date
                        fixes.append(f"Corrected next_invoice_date from {next_date} to {today_date}")

                if fixes:
                    schedule.save()
                    results["fixes_applied"] += 1
                    results["issues"].append(
                        {
                            "schedule": schedule_data.name,
                            "member": schedule_data.member,
                            "billing_frequency": schedule_data.billing_frequency,
                            "issues": issues,
                            "fixes": fixes,
                        }
                    )

            except Exception as e:
                results["issues"].append(
                    {
                        "schedule": schedule_data.name,
                        "member": schedule_data.member,
                        "error": f"Failed to process: {str(e)}",
                    }
                )

        results["issues_found"] = len([i for i in results["issues"] if "fixes" in i])

    except Exception as e:
        results["success"] = False
        results["error"] = str(e)

    return results


def _get_max_future_days(billing_frequency: str) -> int:
    """Get maximum allowed future days based on billing frequency."""
    frequency_days = {
        "Daily": 7,
        "Weekly": 14,
        "Monthly": 62,
        "Quarterly": 100,
        "Annual": 400,
    }
    return frequency_days.get(billing_frequency, 30)
