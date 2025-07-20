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

    # Set the new contribution fields
    membership_type.contribution_mode = "Calculator"
    membership_type.minimum_contribution = 5.0
    membership_type.suggested_contribution = 15.0
    membership_type.maximum_contribution = 150.0
    membership_type.fee_slider_max_multiplier = 10.0
    membership_type.allow_custom_amounts = 1
    membership_type.enable_income_calculator = 1
    membership_type.income_percentage_rate = 0.5
    membership_type.calculator_description = "Our suggested contribution is 0.5% of your monthly net income"

    # Save the membership type
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

    # Test tier-based system
    membership_type.contribution_mode = "Tiers"
    membership_type.predefined_tiers = []

    # Add some test tiers
    tier1 = membership_type.append("predefined_tiers", {})
    tier1.tier_name = "Student"
    tier1.display_name = "Student Membership"
    tier1.amount = 8.0
    tier1.description = "Discounted rate for students"
    tier1.requires_verification = 1
    tier1.is_default = 0
    tier1.display_order = 1

    tier2 = membership_type.append("predefined_tiers", {})
    tier2.tier_name = "Standard"
    tier2.display_name = "Standard Membership"
    tier2.amount = 15.0
    tier2.description = "Standard membership rate"
    tier2.requires_verification = 0
    tier2.is_default = 1
    tier2.display_order = 2

    tier3 = membership_type.append("predefined_tiers", {})
    tier3.tier_name = "Supporter"
    tier3.display_name = "Supporter Membership"
    tier3.amount = 25.0
    tier3.description = "Higher contribution to support our mission"
    tier3.requires_verification = 0
    tier3.is_default = 0
    tier3.display_order = 3

    membership_type.save()

    print(f"✓ Added {len(membership_type.predefined_tiers)} predefined tiers")

    # Test tier-based contribution options
    tier_options = membership_type.get_contribution_options()
    print(f"✓ Tier-based options:")
    print(f"  - Mode: {tier_options['mode']}")
    print(f"  - Tiers: {len(tier_options.get('tiers', []))}")
    for tier in tier_options.get("tiers", []):
        print(f"    - {tier['display_name']}: €{tier['amount']}")

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
    dues_schedule.amount = 15.0
    dues_schedule.status = "Active"
    dues_schedule.auto_generate = 1
    dues_schedule.test_mode = 1

    # Set contribution fields
    dues_schedule.contribution_mode = "Calculator"
    dues_schedule.base_multiplier = 1.0
    dues_schedule.minimum_amount = 5.0
    dues_schedule.suggested_amount = 15.0
    dues_schedule.uses_custom_amount = 0
    # Payment method will be determined dynamically based on member's payment setup

    # Save the dues schedule
    dues_schedule.save()

    print(f"✓ Created membership dues schedule: {dues_schedule.name}")
    print(f"  - Member: {member_name}")
    print(f"  - Contribution mode: {dues_schedule.contribution_mode}")
    print(f"  - Amount: €{dues_schedule.amount}")
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
