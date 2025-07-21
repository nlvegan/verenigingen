#!/usr/bin/env python3
"""
Test script for the new membership dues system
"""
import frappe
from frappe.utils import flt


def test_membership_type_enhancements():
    """Test the enhanced MembershipType with flexible contribution system"""

    # Get or create a test membership type
    membership_type_name = "Test Flexible Membership"

    # Check if it exists
    if frappe.db.exists("Membership Type", membership_type_name):
        membership_type = frappe.get_doc("Membership Type", membership_type_name)
    else:
        # Create new membership type
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = membership_type_name
        membership_type.description = "Test membership type for flexible contribution system"
        membership_type.amount = 15.0
        membership_type.billing_frequency = "Monthly"
        membership_type.is_active = 1

    # Save the membership type
    membership_type.save()

    # Create dues schedule template
    template = frappe.new_doc("Membership Dues Schedule")
    template.is_template = 1
    template.schedule_name = f"Template-{membership_type.name}"
    template.membership_type = membership_type.name
    template.status = "Active"
    template.billing_frequency = getattr(membership_type, "billing_frequency", "Annual")
    template.contribution_mode = "Calculator"
    template.minimum_amount = 5.0
    template.suggested_amount = membership_type.amount or 15.0
    template.invoice_days_before = 30
    template.auto_generate = 1
    template.amount = template.suggested_amount
    template.insert()

    # Link template to membership type
    membership_type.dues_schedule_template = template.name
    membership_type.save()

    print(f"✓ Created/Updated membership type: {membership_type.name}")

    # Test the get_contribution_options method
    options = membership_type.get_contribution_options()

    print(f"✓ Contribution options:")
    print(f"  - Mode: {options['mode']}")
    print(f"  - Minimum: €{options['minimum']}")
    print(f"  - Suggested: €{options['suggested']}")
    print(f"  - Maximum: €{options['maximum']}")
    print(f"  - Calculator enabled: {options['calculator']['enabled']}")
    print(f"  - Quick amounts: {len(options.get('quick_amounts', []))} options")

    return membership_type


def test_membership_dues_schedule():
    """Test the enhanced MembershipDuesSchedule"""

    # Get a test member (assuming there's at least one)
    members = frappe.get_all("Member", limit=1)
    if not members:
        print("⚠ No members found, skipping dues schedule test")
        return

    member_name = members[0].name

    # Get or create a membership for this member
    membership = frappe.db.get_value("Membership", {"member": member_name, "status": "Active"})
    if not membership:
        print("⚠ No active membership found, skipping dues schedule test")
        return

    # Create a test dues schedule
    dues_schedule = frappe.new_doc("Membership Dues Schedule")
    dues_schedule.member = member_name
    dues_schedule.membership = membership
    dues_schedule.billing_frequency = "Monthly"
    dues_schedule.dues_rate = 15.0
    dues_schedule.status = "Active"
    dues_schedule.auto_generate = 1
    dues_schedule.test_mode = 1

    # Set contribution fields
    dues_schedule.contribution_mode = "Calculator"
    dues_schedule.base_multiplier = 1.0
    dues_schedule.minimum_amount = 5.0
    dues_schedule.suggested_amount = 15.0
    dues_schedule.uses_custom_amount = 0

    # Save the dues schedule
    dues_schedule.save()

    print(f"✓ Created membership dues schedule: {dues_schedule.name}")
    print(f"  - Member: {member_name}")
    print(f"  - Contribution mode: {dues_schedule.contribution_mode}")
    print(f"  - Amount: €{dues_schedule.dues_rate}")
    print(f"  - Next invoice: {dues_schedule.next_invoice_date}")

    return dues_schedule


def main():
    """Run all tests"""
    print("Testing new membership dues system...")
    print("=" * 50)

    try:
        # Test membership type enhancements
        membership_type = test_membership_type_enhancements()
        print()

        # Test membership dues schedule
        dues_schedule = test_membership_dues_schedule()
        print()

        print("✓ All tests completed successfully!")

    except Exception as e:
        print(f"✗ Test failed: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
