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
membership_type.billing_frequency = "Monthly"
membership_type.is_active = 1

# Set contribution fields
# contribution_mode moved to dues schedule template
# minimum_contribution moved to dues schedule template
# suggested_contribution moved to dues schedule template
# fee_slider_max_multiplier moved to dues schedule template
# enable_income_calculator moved to dues schedule template
# income_percentage_rate moved to dues schedule template

try:
    membership_type.save()

    # Create dues schedule template
    template = frappe.new_doc("Membership Dues Schedule")
    template.is_template = 1
    template.schedule_name = f"Template-{membership_type.name}"
    template.membership_type = membership_type.name
    template.status = "Active"
    template.billing_frequency = "Annual"
    template.contribution_mode = "Calculator"
    template.minimum_amount = 5.0
    template.suggested_amount = membership_type.amount or 15.0
    template.invoice_days_before = 30
    template.auto_generate = 1
    template.amount = template.suggested_amount
    template.insert()

    membership_type.dues_schedule_template = template.name
    membership_type.save()

    # Create dues schedule template with contribution settings
    template = frappe.new_doc("Membership Dues Schedule")
    template.is_template = 1
    template.schedule_name = f"Template-{membership_type.name}"
    template.membership_type = membership_type.name
    template.status = "Active"
    template.billing_frequency = "Annual"
    template.contribution_mode = "Calculator"  # Update as needed
    template.minimum_amount = 5.0  # Update with actual values
    template.suggested_amount = membership_type.amount or 15.0
    template.invoice_days_before = 30
    template.auto_generate = 1
    template.amount = template.suggested_amount
    template.insert()

    # Link template to membership type
    membership_type.dues_schedule_template = template.name
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
