#!/usr/bin/env python3
"""
Test script for the enhanced membership portal with flexible contribution system
"""

import json

import frappe


def test_create_tier_based_membership():
    """Create a membership type with predefined tiers"""

    # Create a test membership type with tier system
    membership_type = frappe.new_doc("Membership Type")
    membership_type.membership_type_name = "Tier-Based Test Membership"
    membership_type.description = "Test membership type with predefined contribution tiers"
    membership_type.amount = 25.0
    membership_type.billing_frequency = "Annual"
    membership_type.is_active = 1

    # Set contribution system fields
    membership_type.contribution_mode = "Tiers"
    membership_type.minimum_contribution = 10.0
    membership_type.suggested_contribution = 25.0
    membership_type.maximum_contribution = 100.0
    membership_type.fee_slider_max_multiplier = 4.0
    membership_type.allow_custom_amounts = 1
    membership_type.enable_income_calculator = 0  # Disabled for tier-based

    # Add predefined tiers
    student_tier = membership_type.append("predefined_tiers", {})
    student_tier.tier_name = "Student"
    student_tier.display_name = "Student Membership"
    student_tier.amount = 15.0
    student_tier.description = "Discounted rate for students with valid student ID"
    student_tier.requires_verification = 1
    student_tier.is_default = 0
    student_tier.display_order = 1

    standard_tier = membership_type.append("predefined_tiers", {})
    standard_tier.tier_name = "Standard"
    standard_tier.display_name = "Standard Membership"
    standard_tier.amount = 25.0
    standard_tier.description = "Standard membership rate"
    standard_tier.requires_verification = 0
    standard_tier.is_default = 1
    standard_tier.display_order = 2

    supporter_tier = membership_type.append("predefined_tiers", {})
    supporter_tier.tier_name = "Supporter"
    supporter_tier.display_name = "Supporter Membership"
    supporter_tier.amount = 50.0
    supporter_tier.description = "Higher contribution to support our mission"
    supporter_tier.requires_verification = 0
    supporter_tier.is_default = 0
    supporter_tier.display_order = 3

    patron_tier = membership_type.append("predefined_tiers", {})
    patron_tier.tier_name = "Patron"
    patron_tier.display_name = "Patron Membership"
    patron_tier.amount = 100.0
    patron_tier.description = "Premium membership with exclusive benefits"
    patron_tier.requires_verification = 0
    patron_tier.is_default = 0
    patron_tier.display_order = 4

    try:
        membership_type.save()
        print(f"✓ Created tier-based membership type: {membership_type.name}")

        # Test the contribution options
        options = membership_type.get_contribution_options()
        print(f"✓ Contribution mode: {options['mode']}")
        print(f"✓ Number of tiers: {len(options.get('tiers', []))}")

        for tier in options.get("tiers", []):
            default_mark = " (DEFAULT)" if tier["is_default"] else ""
            verification_mark = " (REQUIRES VERIFICATION)" if tier["requires_verification"] else ""
            print(f"  - {tier['display_name']}: €{tier['amount']}{default_mark}{verification_mark}")

        return membership_type

    except Exception as e:
        print(f"✗ Error creating tier-based membership type: {e}")
        return None


def test_create_calculator_based_membership():
    """Create a membership type with income calculator"""

    membership_type = frappe.new_doc("Membership Type")
    membership_type.membership_type_name = "Calculator-Based Test Membership"
    membership_type.description = "Test membership type with income-based calculator"
    membership_type.amount = 15.0
    membership_type.billing_frequency = "Monthly"
    membership_type.is_active = 1

    # Set contribution system fields
    membership_type.contribution_mode = "Calculator"
    membership_type.minimum_contribution = 5.0
    membership_type.suggested_contribution = 15.0
    membership_type.maximum_contribution = 150.0
    membership_type.fee_slider_max_multiplier = 10.0
    membership_type.allow_custom_amounts = 1
    membership_type.enable_income_calculator = 1
    membership_type.income_percentage_rate = 0.75  # 0.75% of monthly income
    membership_type.calculator_description = (
        "We suggest 0.75% of your monthly net income as a fair contribution"
    )

    try:
        membership_type.save()
        print(f"✓ Created calculator-based membership type: {membership_type.name}")

        # Test the contribution options
        options = membership_type.get_contribution_options()
        print(f"✓ Contribution mode: {options['mode']}")
        print(f"✓ Calculator enabled: {options['calculator']['enabled']}")
        print(f"✓ Income percentage: {options['calculator']['percentage']}%")
        print(f"✓ Number of quick amounts: {len(options.get('quick_amounts', []))}")

        for amount in options.get("quick_amounts", []):
            default_mark = " (DEFAULT)" if amount["is_default"] else ""
            print(f"  - {amount['label']}: €{amount['amount']:.2f}{default_mark}")

        return membership_type

    except Exception as e:
        print(f"✗ Error creating calculator-based membership type: {e}")
        return None


def test_create_flexible_membership():
    """Create a membership type that supports both tiers and calculator"""

    membership_type = frappe.new_doc("Membership Type")
    membership_type.membership_type_name = "Flexible Test Membership"
    membership_type.description = "Test membership type with both tiers and calculator options"
    membership_type.amount = 20.0
    membership_type.billing_frequency = "Monthly"
    membership_type.is_active = 1

    # Set contribution system fields
    membership_type.contribution_mode = "Both"
    membership_type.minimum_contribution = 8.0
    membership_type.suggested_contribution = 20.0
    membership_type.maximum_contribution = 200.0
    membership_type.fee_slider_max_multiplier = 10.0
    membership_type.allow_custom_amounts = 1
    membership_type.enable_income_calculator = 1
    membership_type.income_percentage_rate = 0.6
    membership_type.calculator_description = (
        "Calculate 0.6% of monthly income or choose from predefined tiers"
    )

    # Add a few tiers
    basic_tier = membership_type.append("predefined_tiers", {})
    basic_tier.tier_name = "Basic"
    basic_tier.display_name = "Basic Membership"
    basic_tier.amount = 15.0
    basic_tier.description = "Basic membership level"
    basic_tier.requires_verification = 0
    basic_tier.is_default = 0
    basic_tier.display_order = 1

    plus_tier = membership_type.append("predefined_tiers", {})
    plus_tier.tier_name = "Plus"
    plus_tier.display_name = "Plus Membership"
    plus_tier.amount = 20.0
    plus_tier.description = "Standard membership level"
    plus_tier.requires_verification = 0
    plus_tier.is_default = 1
    plus_tier.display_order = 2

    premium_tier = membership_type.append("predefined_tiers", {})
    premium_tier.tier_name = "Premium"
    premium_tier.display_name = "Premium Membership"
    premium_tier.amount = 35.0
    premium_tier.description = "Premium membership with extra benefits"
    premium_tier.requires_verification = 0
    premium_tier.is_default = 0
    premium_tier.display_order = 3

    try:
        membership_type.save()
        print(f"✓ Created flexible membership type: {membership_type.name}")

        # Test the contribution options
        options = membership_type.get_contribution_options()
        print(f"✓ Contribution mode: {options['mode']}")
        print(f"✓ Has tiers: {len(options.get('tiers', [])) > 0}")
        print(f"✓ Has calculator: {options['calculator']['enabled']}")
        print(f"✓ Has quick amounts: {len(options.get('quick_amounts', [])) > 0}")

        return membership_type

    except Exception as e:
        print(f"✗ Error creating flexible membership type: {e}")
        return None


def test_enhanced_api():
    """Test the enhanced API endpoints"""

    print("\n" + "=" * 60)
    print("Testing Enhanced API Endpoints")
    print("=" * 60)

    try:
        # Test get membership types
        from verenigingen.api.enhanced_membership_application import get_membership_types_for_application

        membership_types = get_membership_types_for_application()

        print(f"✓ Retrieved {len(membership_types)} membership types")

        # Show a few examples
        for i, mt in enumerate(membership_types[:3]):
            print(f"  {i+1}. {mt['membership_type_name']} - Mode: {mt['contribution_options']['mode']}")

        # Test contribution validation
        from verenigingen.templates.pages.enhanced_membership_application import validate_contribution_amount

        if membership_types:
            test_mt = membership_types[0]["name"]
            validation = validate_contribution_amount(test_mt, 25.0, "Calculator", None, 1.5)

            if validation["valid"]:
                print(f"✓ Contribution validation passed for €25.00")
            else:
                print(f"✗ Contribution validation failed: {validation['error']}")

        return True

    except Exception as e:
        print(f"✗ API test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("Testing Enhanced Membership Portal System")
    print("=" * 60)

    try:
        # Test creating different types of membership configurations
        tier_based = test_create_tier_based_membership()
        print()

        calculator_based = test_create_calculator_based_membership()
        print()

        flexible = test_create_flexible_membership()
        print()

        # Test API functionality
        api_success = test_enhanced_api()

        # Summary
        print("\n" + "=" * 60)
        print("Test Summary")
        print("=" * 60)

        results = [
            ("Tier-based membership", tier_based is not None),
            ("Calculator-based membership", calculator_based is not None),
            ("Flexible membership", flexible is not None),
            ("API endpoints", api_success),
        ]

        for test_name, success in results:
            status = "✓ PASS" if success else "✗ FAIL"
            print(f"{test_name:30} {status}")

        total_passed = sum(1 for _, success in results if success)
        print(f"\nPassed: {total_passed}/{len(results)} tests")

        if total_passed == len(results):
            print("\n🎉 All tests passed! The enhanced membership portal is working correctly.")
        else:
            print(f"\n⚠️  {len(results) - total_passed} test(s) failed. Please check the errors above.")

    except Exception as e:
        print(f"✗ Test execution failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
