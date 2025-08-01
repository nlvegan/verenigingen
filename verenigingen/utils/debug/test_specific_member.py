#!/usr/bin/env python3
"""
Test script to validate specific member dues schedule creation
"""

import frappe
from frappe.utils import today


def test_specific_member(member_name="Assoc-Member-2025-07-4062"):
    """Test dues schedule creation for a specific member"""
    print(f"=== Testing Member: {member_name} ===")

    try:
        # Check if member exists
        member_doc = frappe.get_doc("Member", member_name)
        print(f"✓ Member found: {member_doc.full_name}")

        # Check existing dues schedule
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member_name, "is_template": 0}, "name"
        )

        if existing_schedule:
            print(f"✓ Member already has dues schedule: {existing_schedule}")
            schedule_doc = frappe.get_doc("Membership Dues Schedule", existing_schedule)
            print(f"  - Status: {schedule_doc.status}")
            print(f"  - Dues Rate: €{schedule_doc.dues_rate}")
            print(f"  - Billing Frequency: {schedule_doc.billing_frequency}")
            return True
        else:
            print("✗ Member has no dues schedule")

        # Check active membership
        active_memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name, "docstatus": 1},
            fields=["name", "status", "membership_type", "start_date", "renewal_date"],
            order_by="creation desc",
        )

        print(f"Found {len(active_memberships)} memberships:")
        for membership in active_memberships:
            print(f"  - {membership.name}: {membership.status} ({membership.membership_type})")
            print(f"    Period: {membership.start_date} to {membership.renewal_date}")

        # Find active membership
        active_membership = None
        for membership in active_memberships:
            if membership.status == "Active":
                active_membership = membership
                break

        if not active_membership:
            print("✗ No active membership found")
            # Check if we can create one for testing
            if active_memberships:
                latest = active_memberships[0]
                print(f"Latest membership: {latest.name} ({latest.status})")

                # Check if we can manually trigger the hook
                membership_doc = frappe.get_doc("Membership", latest.name)
                if latest.status == "Active":
                    print("Attempting to trigger dues schedule creation...")
                    try:
                        membership_doc.create_or_update_dues_schedule()
                        print("✓ Hook executed successfully")

                        # Check if schedule was created
                        new_schedule = frappe.db.get_value(
                            "Membership Dues Schedule", {"member": member_name, "is_template": 0}, "name"
                        )

                        if new_schedule:
                            print(f"✓ Dues schedule created: {new_schedule}")
                        else:
                            print("✗ No dues schedule created after manual trigger")

                    except Exception as e:
                        print(f"✗ Hook execution failed: {str(e)}")
            return False

        print(f"✓ Active membership: {active_membership.name}")
        print(f"  - Type: {active_membership.membership_type}")

        # Check membership type template
        if active_membership.membership_type:
            membership_type_doc = frappe.get_doc("Membership Type", active_membership.membership_type)
            if membership_type_doc.dues_schedule_template:
                print(f"✓ Template configured: {membership_type_doc.dues_schedule_template}")

                # Validate template
                template = frappe.get_doc(
                    "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                )
                print(f"  - Template amount: €{template.suggested_amount}")
                print(f"  - Template billing: {template.billing_frequency}")

                # Try to create dues schedule
                print("Attempting to create dues schedule...")
                membership_doc = frappe.get_doc("Membership", active_membership.name)
                try:
                    membership_doc.create_or_update_dues_schedule()
                    print("✓ Dues schedule creation attempted")

                    # Check result
                    new_schedule = frappe.db.get_value(
                        "Membership Dues Schedule", {"member": member_name, "is_template": 0}, "name"
                    )

                    if new_schedule:
                        print(f"✓ Dues schedule created: {new_schedule}")
                        return True
                    else:
                        print("✗ No dues schedule created")
                        return False

                except Exception as e:
                    print(f"✗ Creation failed: {str(e)}")
                    return False
            else:
                print(f"✗ No template configured for membership type: {active_membership.membership_type}")
                return False

        return False

    except frappe.DoesNotExistError:
        print(f"✗ Member {member_name} not found")
        return False
    except Exception as e:
        print(f"✗ Test failed: {str(e)}")
        return False


def test_scheduled_task_for_member(member_name="Assoc-Member-2025-07-4062"):
    """Test if scheduled task would pick up this member"""
    print(f"\n=== Testing Scheduled Task Detection for {member_name} ===")

    try:
        # Check if member would be detected by scheduled task query
        result = frappe.db.sql(
            """
            SELECT
                m.name as membership_name,
                m.member as member_name,
                m.membership_type,
                mem.full_name,
                mem.member_id,
                mt.minimum_amount as membership_type_amount
            FROM `tabMembership` m
            INNER JOIN `tabMember` mem ON m.member = mem.name
            LEFT JOIN `tabMembership Type` mt ON m.membership_type = mt.name
            WHERE
                m.status = 'Active'
                AND m.docstatus = 1
                AND m.membership_type IS NOT NULL
                AND m.member = %s
                AND NOT EXISTS (
                    SELECT 1
                    FROM `tabMembership Dues Schedule` mds
                    WHERE mds.member = m.member
                    AND mds.status = 'Active'
                )
        """,
            member_name,
            as_dict=True,
        )

        if result:
            member_info = result[0]
            print(f"✓ Member would be detected by scheduled task:")
            print(f"  - Membership: {member_info.membership_name}")
            print(f"  - Type: {member_info.membership_type}")
            print(f"  - Full Name: {member_info.full_name}")
            return True
        else:
            print("✗ Member would NOT be detected by scheduled task")
            print("Reasons could be:")
            print("  - Already has active dues schedule")
            print("  - No active membership")
            print("  - Membership not submitted")
            print("  - No membership type assigned")
            return False

    except Exception as e:
        print(f"✗ Scheduled task test failed: {str(e)}")
        return False


def main():
    """Run specific member tests"""
    member_name = "Assoc-Member-2025-07-4062"

    print(f"=== Specific Member Dues Schedule Test ===")
    print(f"Date: {today()}")
    print(f"Site: {frappe.local.site}")
    print(f"Target Member: {member_name}")

    test1_result = test_specific_member(member_name)
    test2_result = test_scheduled_task_for_member(member_name)

    print(f"\n=== Test Summary ===")
    print(f"Member Test: {'✓ PASS' if test1_result else '✗ FAIL'}")
    print(f"Scheduled Task Test: {'✓ PASS' if test2_result else '✗ FAIL'}")

    if test1_result and test2_result:
        print("🎉 All tests passed!")
    else:
        print("⚠️  Some tests failed. Review the output above.")


if __name__ == "__main__":
    main()
