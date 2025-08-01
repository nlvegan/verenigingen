#!/usr/bin/env python3
"""
Test the fix with an existing member

Created: 2025-08-01
Purpose: Test the fix with the actual member that had the issue
TODO: Remove after verification complete
"""

import frappe


def test_existing_member_fix():
    """Test the fix with an existing member"""

    print("Testing Fix with Existing Member")
    print("=" * 40)

    member_name = "Assoc-Member-2025-07-4218"

    try:
        # Get the existing member
        member = frappe.get_doc("Member", member_name)
        print(f"Current member dues_rate: €{member.dues_rate:.2f}")

        # Get existing schedule
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member_name, "is_template": 0}
        )
        if existing_schedule:
            schedule = frappe.get_doc("Membership Dues Schedule", existing_schedule)
            print(f"Current schedule dues_rate: €{schedule.dues_rate:.2f}")
            print(f"Current schedule contribution_mode: {schedule.contribution_mode}")

            # Temporarily change member's dues_rate to simulate user selected €6.00
            original_dues_rate = member.dues_rate
            member.dues_rate = 6.0
            member.fee_override_reason = "Testing: User selected €6.00 during application"
            member.save(ignore_permissions=True)
            print(f"✅ Updated member dues_rate to €{member.dues_rate:.2f}")

            # Delete and recreate the schedule to test the new logic
            schedule_backup = {
                "name": schedule.name,
                "dues_rate": schedule.dues_rate,
                "contribution_mode": schedule.contribution_mode,
                "membership": schedule.membership,
                "member": schedule.member,
            }

            print(f"Deleting existing schedule: {schedule.name}")
            frappe.delete_doc("Membership Dues Schedule", schedule.name, force=True)

            # Now test creating a new schedule with the new logic
            print("Creating new schedule with sophisticated logic...")

            from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
                MembershipDuesSchedule,
            )

            # Get membership info
            membership = frappe.db.get_value("Membership", {"member": member_name, "status": "Active"})
            membership_type = frappe.db.get_value("Membership", membership, "membership_type")

            new_schedule_name = MembershipDuesSchedule.create_from_template(
                member_name=member_name, membership_type=membership_type, membership_name=membership
            )

            print(f"✅ New schedule created: {new_schedule_name}")

            # Check the results
            new_schedule = frappe.get_doc("Membership Dues Schedule", new_schedule_name)
            print(f"\n📊 Results:")
            print(f"New schedule dues_rate: €{new_schedule.dues_rate:.2f}")
            print(f"New schedule contribution_mode: {new_schedule.contribution_mode}")
            print(f"New schedule uses_custom_amount: {getattr(new_schedule, 'uses_custom_amount', 'None')}")
            print(
                f"New schedule custom_amount_reason: {getattr(new_schedule, 'custom_amount_reason', 'None')}"
            )

            if new_schedule.dues_rate == 6.0:
                print("✅ SUCCESS: User's selected dues rate (€6.00) was preserved!")
            else:
                print(f"❌ FAILURE: Expected €6.00, got €{new_schedule.dues_rate:.2f}")

            # Restore original state
            print("\n🔄 Restoring original state...")
            frappe.delete_doc("Membership Dues Schedule", new_schedule_name, force=True)

            # Recreate original schedule
            restored_schedule = frappe.new_doc("Membership Dues Schedule")
            restored_schedule.member = schedule_backup["member"]
            restored_schedule.membership = schedule_backup["membership"]
            restored_schedule.dues_rate = schedule_backup["dues_rate"]
            restored_schedule.contribution_mode = schedule_backup["contribution_mode"]
            restored_schedule.membership_type = membership_type
            restored_schedule.billing_frequency = "Monthly"
            restored_schedule.status = "Active"
            restored_schedule.is_template = 0
            restored_schedule.insert(ignore_permissions=True)

            # Restore member dues_rate
            member.dues_rate = original_dues_rate
            member.save(ignore_permissions=True)

            print(f"✅ Restored original schedule and member dues_rate to €{original_dues_rate:.2f}")

        else:
            print("❌ No existing schedule found")

    except Exception as e:
        print(f"❌ Error during test: {str(e)}")
        raise e

    print("\n" + "=" * 40)
    print("Existing member test completed")


if __name__ == "__main__":
    test_existing_member_fix()
