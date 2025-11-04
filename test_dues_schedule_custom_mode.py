#!/usr/bin/env python3
"""
Test script to verify Membership Dues Schedule custom contribution mode with 0 suggested amount
"""
import frappe
from frappe.utils import today


def test_custom_mode_zero_suggested_amount():
    """Test that custom contribution mode allows 0 suggested amount"""
    frappe.connect(site="dev.veganisme.net")
    frappe.set_user("Administrator")

    # First, check if we have a test membership type
    membership_type_name = "Test Custom Mode Type"

    # Create or get membership type
    if frappe.db.exists("Membership Type", membership_type_name):
        membership_type = frappe.get_doc("Membership Type", membership_type_name)
    else:
        print(f"Creating test membership type: {membership_type_name}")
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = membership_type_name
        membership_type.minimum_amount = 0  # 0 euro minimum
        membership_type.insert(ignore_permissions=True)

    # Create template with custom contribution mode
    template_name = "Test Custom Template"
    if frappe.db.exists("Membership Dues Schedule", template_name):
        template = frappe.get_doc("Membership Dues Schedule", template_name)
        frappe.delete_doc("Membership Dues Schedule", template_name, force=True)

    print(f"\nCreating dues schedule template with Custom contribution mode...")
    template = frappe.new_doc("Membership Dues Schedule")
    template.schedule_name = template_name
    template.is_template = 1
    template.membership_type = membership_type.name
    template.contribution_mode = "Custom"
    template.suggested_amount = 0  # This should be allowed for Custom mode
    template.billing_frequency = "Monthly"

    try:
        template.insert(ignore_permissions=True)
        print(f"✅ SUCCESS: Template created with custom mode and 0 suggested amount")
        print(f"   Template: {template.name}")
        print(f"   Contribution Mode: {template.contribution_mode}")
        print(f"   Suggested Amount: €{template.suggested_amount}")
        print(f"   Minimum Amount: €{template.minimum_amount}")

        # Update the membership type to use this template
        membership_type.dues_schedule_template = template.name
        membership_type.save(ignore_permissions=True)
        print(f"✅ Membership type updated to use template")

        return True

    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        frappe.db.commit()


def test_calculator_mode_requires_suggested_amount():
    """Test that Calculator mode still requires suggested_amount > 0"""
    frappe.connect(site="dev.veganisme.net")
    frappe.set_user("Administrator")

    membership_type_name = "Test Calculator Mode Type"

    # Create or get membership type
    if frappe.db.exists("Membership Type", membership_type_name):
        membership_type = frappe.get_doc("Membership Type", membership_type_name)
    else:
        print(f"\nCreating test membership type: {membership_type_name}")
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = membership_type_name
        membership_type.minimum_amount = 5
        membership_type.insert(ignore_permissions=True)

    # Try to create template with Calculator mode but 0 suggested amount
    template_name = "Test Calculator Template"
    if frappe.db.exists("Membership Dues Schedule", template_name):
        frappe.delete_doc("Membership Dues Schedule", template_name, force=True)

    print(f"\nAttempting to create Calculator mode template with 0 suggested amount...")
    template = frappe.new_doc("Membership Dues Schedule")
    template.schedule_name = template_name
    template.is_template = 1
    template.membership_type = membership_type.name
    template.contribution_mode = "Calculator"
    template.suggested_amount = 0
    template.billing_frequency = "Monthly"

    # Update membership type to use this template
    membership_type.dues_schedule_template = template.name
    membership_type.save(ignore_permissions=True)

    try:
        template.insert(ignore_permissions=True)
        print(f"❌ UNEXPECTED: Template should have failed validation but didn't")
        return False

    except frappe.exceptions.ValidationError as e:
        if "Calculator mode must have a suggested_amount" in str(e):
            print(f"✅ SUCCESS: Calculator mode correctly requires suggested_amount")
            print(f"   Error message: {str(e)}")
            return True
        else:
            print(f"❌ FAILED: Wrong error message: {str(e)}")
            return False

    except Exception as e:
        print(f"❌ FAILED: Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        frappe.db.rollback()


if __name__ == "__main__":
    print("=" * 80)
    print("Testing Membership Dues Schedule Contribution Mode Validation")
    print("=" * 80)

    test1 = test_custom_mode_zero_suggested_amount()
    test2 = test_calculator_mode_requires_suggested_amount()

    print("\n" + "=" * 80)
    print("Test Results:")
    print("=" * 80)
    print(f"Custom mode with 0 suggested amount: {'✅ PASSED' if test1 else '❌ FAILED'}")
    print(f"Calculator mode validation: {'✅ PASSED' if test2 else '❌ FAILED'}")
    print("=" * 80)
