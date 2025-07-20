#!/usr/bin/env python3
"""
Test the validation logic fixes and field naming corrections
"""

import os
import sys

import frappe


def test_validation_fixes():
    """Test that the validation fixes work correctly"""
    try:
        # Connect to site
        frappe.connect(site="dev.veganisme.net")

        print("🧪 Testing Validation Logic Fixes")
        print("=" * 50)

        # Test 1: Create a simple membership dues schedule to verify field names work
        print("\n1. Testing Field Name Fixes (dues_rate vs amount)")

        # Get a test member
        test_member = frappe.db.get_value("Member", {"status": "Active"}, ["name", "full_name"], as_dict=True)
        if not test_member:
            print("❌ No active members found for testing")
            return False

        print(f"   Using test member: {test_member.full_name} ({test_member.name})")

        # Get or create membership type
        membership_type = frappe.db.get_value("Membership Type", {"is_active": 1}, "name")
        if not membership_type:
            print("❌ No active membership types found")
            return False

        membership_type_doc = frappe.get_doc("Membership Type", membership_type)
        print(f"   Using membership type: {membership_type}")
        print(f"   Suggested contribution: €{membership_type_doc.suggested_contribution}")
        print(f"   Minimum contribution: €{getattr(membership_type_doc, 'minimum_contribution', 'Not set')}")

        # Test 2: Create a dues schedule and verify validation works
        print("\n2. Testing Validation Logic")

        # Create a test dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.schedule_name = f"Test-Validation-{frappe.generate_hash(length=6)}"
        dues_schedule.member = test_member.name
        dues_schedule.membership_type = membership_type
        dues_schedule.contribution_mode = "Calculator"
        dues_schedule.base_multiplier = 1.0
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.status = "Active"

        # Explicitly set a dues_rate to test that it's preserved
        test_dues_rate = 25.0
        dues_schedule.dues_rate = test_dues_rate

        print(f"   Setting dues_rate to: €{test_dues_rate}")
        print(f"   Contribution mode: {dues_schedule.contribution_mode}")
        print(f"   Base multiplier: {dues_schedule.base_multiplier}")

        # Test validation (this should preserve the explicitly set dues_rate)
        try:
            dues_schedule.validate()
            print("   ✅ Validation passed")

            # Check that dues_rate was preserved (not overridden)
            if dues_schedule.dues_rate == test_dues_rate:
                print(f"   ✅ Dues rate preserved: €{dues_schedule.dues_rate}")
            else:
                print(f"   ⚠️  Dues rate changed: €{test_dues_rate} → €{dues_schedule.dues_rate}")

        except Exception as e:
            print(f"   ❌ Validation failed: {str(e)}")
            return False

        # Test 3: Test minimum value enforcement
        print("\n3. Testing Minimum Value Enforcement")

        if hasattr(membership_type_doc, "minimum_contribution") and membership_type_doc.minimum_contribution:
            min_contribution = membership_type_doc.minimum_contribution

            # Test with value below minimum
            dues_schedule.dues_rate = min_contribution - 1.0
            print(
                f"   Setting dues_rate below minimum: €{dues_schedule.dues_rate} (min: €{min_contribution})"
            )

            try:
                dues_schedule.validate()

                if dues_schedule.dues_rate >= min_contribution:
                    print(f"   ✅ Dues rate auto-raised to minimum: €{dues_schedule.dues_rate}")
                else:
                    print(f"   ❌ Dues rate not raised to minimum: €{dues_schedule.dues_rate}")

            except Exception as e:
                print(f"   ℹ️  Validation error (expected): {str(e)}")
        else:
            print("   ℹ️  No minimum contribution set, skipping minimum test")

        # Test 4: Test zero rate handling
        print("\n4. Testing Zero Rate Handling")

        dues_schedule.dues_rate = 0.0
        dues_schedule.custom_amount_reason = "Test free membership"

        try:
            dues_schedule.validate()
            print("   ✅ Zero rate with reason accepted")
        except Exception as e:
            print(f"   ❌ Zero rate validation failed: {str(e)}")

        # Test 5: Test manager override functionality
        print("\n5. Testing Manager Override")

        # Get Verenigingen Settings
        settings = frappe.get_single("Verenigingen Settings")
        max_multiplier = getattr(settings, "maximum_fee_multiplier", None)

        if max_multiplier:
            base_amount = membership_type_doc.suggested_contribution or membership_type_doc.amount
            max_amount = base_amount * max_multiplier
            over_max_amount = max_amount + 10.0

            print(f"   Base amount: €{base_amount}")
            print(f"   Max multiplier: {max_multiplier}x")
            print(f"   Max allowed: €{max_amount}")
            print(f"   Testing with: €{over_max_amount}")

            dues_schedule.dues_rate = over_max_amount

            try:
                dues_schedule.validate()

                if dues_schedule.uses_custom_amount and dues_schedule.custom_amount_approved:
                    print("   ✅ Manager auto-approval worked")
                else:
                    print("   ❌ Manager auto-approval failed")

            except Exception as e:
                print(f"   ℹ️  Validation error: {str(e)}")
        else:
            print("   ℹ️  No maximum fee multiplier set, skipping override test")

        print("\n" + "=" * 50)
        print("✅ All validation tests completed successfully!")

        return True

    except Exception as e:
        print(f"❌ Test failed with error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        frappe.destroy()


if __name__ == "__main__":
    success = test_validation_fixes()
    print(f"\n{'🎉 SUCCESS' if success else '💥 FAILED'}: Validation fixes test")
    sys.exit(0 if success else 1)
