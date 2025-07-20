#!/usr/bin/env python3
"""
Test the dues rate validation fix for MEMB-25-07-2556
"""

import os
import sys

import frappe

# Add the bench apps path
sys.path.append("/home/frappe/frappe-bench/apps")


def test_membership_submission():
    # Connect to the site
    frappe.connect(site="dev.veganisme.net")

    try:
        # Get the membership document
        membership = frappe.get_doc("Membership", "MEMB-25-07-2556")

        print(f"Testing membership: {membership.name}")
        print(f"Member: {membership.member}")
        print(f"Current status: {membership.status}")
        print(f"Current docstatus: {membership.docstatus}")

        # Check if this membership has a dues schedule
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": membership.member, "is_template": 0},
            ["name", "dues_rate", "contribution_mode", "base_multiplier"],
            as_dict=True,
        )

        if dues_schedule:
            print(f"Dues schedule: {dues_schedule.name}")
            print(f"Current dues rate: {dues_schedule.dues_rate}")
            print(f"Contribution mode: {dues_schedule.contribution_mode}")
            print(f"Base multiplier: {dues_schedule.base_multiplier}")

            # Get the membership type details
            membership_type = frappe.get_doc("Membership Type", membership.membership_type)
            print(f"Membership type: {membership.membership_type}")
            print(f"Suggested contribution: {getattr(membership_type, 'suggested_contribution', 'None')}")
            print(f"Amount: {getattr(membership_type, 'amount', 'None')}")

            # Test the validation logic (simulate what happens during save)
            try:
                schedule_doc = frappe.get_doc("Membership Dues Schedule", dues_schedule.name)
                print(f"Schedule loaded successfully")

                # Call validate method to test the fix
                schedule_doc.validate()
                print("✅ Validation passed - no errors!")

                return True

            except Exception as e:
                print(f"❌ Validation failed: {str(e)}")
                return False
        else:
            print("No dues schedule found for this member")
            return False

    except Exception as e:
        print(f"Error: {str(e)}")
        return False

    finally:
        frappe.destroy()


if __name__ == "__main__":
    success = test_membership_submission()
    sys.exit(0 if success else 1)
