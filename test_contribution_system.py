#!/usr/bin/env python3
"""
Simple test to verify the new contribution system works
"""

# Test the contribution options API directly
import frappe

# Test creating a membership type with new fields
membership_type = frappe.new_doc("Membership Type")
membership_type.membership_type_name = "Test Flexible System"
membership_type.description = "Test for flexible contribution system"
membership_type.amount = 15.0
membership_type.subscription_period = "Monthly"
membership_type.is_active = 1

# Set contribution fields
membership_type.contribution_mode = "Calculator"
membership_type.minimum_contribution = 5.0
membership_type.suggested_contribution = 15.0
membership_type.fee_slider_max_multiplier = 10.0
membership_type.enable_income_calculator = 1
membership_type.income_percentage_rate = 0.5

try:
    membership_type.save()
    print(f"✓ Created membership type: {membership_type.name}")

    # Test the API
    options = membership_type.get_contribution_options()
    print(f"✓ Options: {options}")

    # Test with the whitelist API
    from verenigingen.verenigingen.doctype.membership_type.membership_type import (
        get_membership_contribution_options,
    )

    api_options = get_membership_contribution_options(membership_type.name)
    print(f"✓ API Options: {api_options}")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback

    traceback.print_exc()
