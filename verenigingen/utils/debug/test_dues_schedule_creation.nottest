#!/usr/bin/env python3
"""
Test script to validate dues schedule creation hooks and scheduled tasks
"""

import frappe
from frappe.utils import today


def test_hook_registration():
    """Test that hooks are properly registered"""
    from verenigingen import hooks

    print("=== Testing Hook Registration ===")

    # Check if Membership hooks are registered
    membership_hooks = hooks.doc_events.get("Membership", {})
    print(f"Membership hooks registered: {list(membership_hooks.keys())}")

    # Verify on_submit hook exists
    on_submit = membership_hooks.get("on_submit")
    if on_submit:
        print(f"✓ on_submit hook registered: {on_submit}")
    else:
        print("✗ on_submit hook NOT registered")

    # Check scheduled task registration
    daily_tasks = hooks.scheduler_events.get("daily", [])
    dues_schedule_tasks = [task for task in daily_tasks if "dues_schedule" in task]
    print(f"Dues schedule scheduled tasks: {dues_schedule_tasks}")

    return len(membership_hooks) > 0 and on_submit is not None


def test_membership_hook_execution():
    """Test membership hook execution by creating a test membership"""
    print("\n=== Testing Membership Hook Execution ===")

    try:
        # Find a member without a dues schedule for testing
        members_without_schedules = frappe.db.sql(
            """
            SELECT m.name
            FROM `tabMember` m
            LEFT JOIN `tabMembership Dues Schedule` mds ON mds.member = m.name AND mds.is_template = 0
            WHERE mds.name IS NULL
            LIMIT 1
        """,
            as_dict=True,
        )

        if not members_without_schedules:
            print("✓ All members have dues schedules (or no eligible members found)")
            return True

        test_member = members_without_schedules[0].name
        print(f"Testing with member: {test_member}")

        # Check if member has active membership type
        membership_info = frappe.db.get_value(
            "Membership",
            {"member": test_member, "status": "Active", "docstatus": 1},
            ["name", "membership_type"],
            as_dict=True,
        )

        if not membership_info:
            print("✓ No active membership found for testing (expected)")
            return True

        print(f"Active membership: {membership_info.name}, Type: {membership_info.membership_type}")

        # Check if membership type has template
        membership_type_doc = frappe.get_doc("Membership Type", membership_info.membership_type)
        if not membership_type_doc.dues_schedule_template:
            print(f"✗ Membership type {membership_info.membership_type} has no dues schedule template")
            return False

        print(f"✓ Template configured: {membership_type_doc.dues_schedule_template}")

        # Test the hook by calling it directly
        membership_doc = frappe.get_doc("Membership", membership_info.name)

        try:
            membership_doc.create_or_update_dues_schedule()
            print("✓ Hook executed successfully")

            # Check if schedule was created
            schedule = frappe.db.get_value(
                "Membership Dues Schedule", {"member": test_member, "is_template": 0}, "name"
            )

            if schedule:
                print(f"✓ Dues schedule created: {schedule}")
                return True
            else:
                print("✗ No dues schedule created after hook execution")
                return False

        except Exception as e:
            print(f"✗ Hook execution failed: {str(e)}")
            return False

    except Exception as e:
        print(f"✗ Test setup failed: {str(e)}")
        return False


def test_scheduled_task_logic():
    """Test the scheduled task for auto-creating dues schedules"""
    print("\n=== Testing Scheduled Task Logic ===")

    try:
        from verenigingen.utils.dues_schedule_auto_creator import preview_missing_dues_schedules

        # Preview what would be processed
        preview_results = preview_missing_dues_schedules()
        print(f"Members without dues schedules: {len(preview_results)}")

        if preview_results:
            for member in preview_results[:3]:  # Show first 3
                print(f"  - {member.full_name} ({member.membership_type})")

        # Test the query logic
        missing_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabMembership` m
            INNER JOIN `tabMember` mem ON m.member = mem.name
            WHERE
                m.status = 'Active'
                AND m.docstatus = 1
                AND m.membership_type IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM `tabMembership Dues Schedule` mds
                    WHERE mds.member = m.member
                    AND mds.status = 'Active'
                )
        """,
            as_dict=True,
        )[0].count

        print(f"✓ Query logic works: {missing_count} members need schedules")
        return True

    except Exception as e:
        print(f"✗ Scheduled task test failed: {str(e)}")
        return False


def test_dues_template_validation():
    """Test that membership types have proper dues schedule templates"""
    print("\n=== Testing Dues Template Validation ===")

    try:
        # Get all active membership types
        membership_types = frappe.get_all(
            "Membership Type", filters={"is_active": 1}, fields=["name", "dues_schedule_template"]
        )

        valid_types = 0
        for mt in membership_types:
            if mt.dues_schedule_template:
                # Validate template exists and is configured
                try:
                    template = frappe.get_doc("Membership Dues Schedule", mt.dues_schedule_template)
                    if template.is_template and template.suggested_amount:
                        valid_types += 1
                        print(
                            f"✓ {mt.name}: Template {mt.dues_schedule_template} (€{template.suggested_amount})"
                        )
                    else:
                        print(
                            f"✗ {mt.name}: Template {mt.dues_schedule_template} invalid (not template or no amount)"
                        )
                except:
                    print(f"✗ {mt.name}: Template {mt.dues_schedule_template} not found")
            else:
                print(f"✗ {mt.name}: No template assigned")

        print(f"Valid membership types with templates: {valid_types}/{len(membership_types)}")
        return valid_types == len(membership_types)

    except Exception as e:
        print(f"✗ Template validation failed: {str(e)}")
        return False


def main():
    """Run all tests and provide summary"""
    print(f"=== Dues Schedule Creation System Validation ===")
    print(f"Date: {today()}")
    print(f"Site: {frappe.local.site}")

    results = {
        "Hook Registration": test_hook_registration(),
        "Hook Execution": test_membership_hook_execution(),
        "Scheduled Task Logic": test_scheduled_task_logic(),
        "Template Validation": test_dues_template_validation(),
    }

    print(f"\n=== Test Summary ===")
    total_tests = len(results)
    passed_tests = sum(results.values())

    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name}: {status}")

    print(f"\nOverall: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 All tests passed! Dues schedule creation system is working correctly.")
    else:
        print("⚠️  Some tests failed. Review the issues above.")

    return passed_tests == total_tests


if __name__ == "__main__":
    main()
