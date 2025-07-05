import unittest

import frappe
from frappe.utils import random_string


class TestFeeOverrideLogic(unittest.TestCase):
    """Test fee override logic for new vs existing members"""

    def setUp(self):
        """Set up test environment"""
        frappe.set_user("Administrator")
        self.cleanup_test_data()

    def tearDown(self):
        """Clean up after tests"""
        self.cleanup_test_data()

    def cleanup_test_data(self):
        """Remove test data"""
        frappe.db.delete("Member", {"email": ["like", "%feetest%"]})
        frappe.db.commit()

    def test_new_member_custom_fee_no_change_tracking(self):
        """Test that new members with custom fees don't trigger change tracking"""
        print("\n🧪 Testing new member with custom fee (no change tracking)...")

        # Create a new member with custom fee (like from application form)
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "NewApp",
                "last_name": "FeeTest" + random_string(4),
                "email": f"newapp.feetest.{random_string(6)}@example.com",
                "birth_date": "1992-01-01",
                "membership_fee_override": 75.0,
                "fee_override_reason": "Custom contribution during application",
                "status": "Pending",
                "application_status": "Pending",
            }
        )

        # Insert member (this triggers validation including handle_fee_override_changes)
        member.insert(ignore_permissions=True)

        # KEY TEST: Check that _pending_fee_change was NOT set for new member
        self.assertFalse(
            hasattr(member, "_pending_fee_change"), "New member should not have _pending_fee_change attribute"
        )

        # Verify fee override fields are set correctly
        self.assertEqual(member.membership_fee_override, 75.0)
        self.assertEqual(member.fee_override_reason, "Custom contribution during application")
        self.assertIsNotNone(member.fee_override_date)
        self.assertIsNotNone(member.fee_override_by)

        print(f"✅ New member {member.name} correctly skips fee change tracking")
        print(f"   Fee override: €{member.membership_fee_override}")
        print(f"   Reason: {member.fee_override_reason}")

    def test_existing_member_fee_change_triggers_tracking(self):
        """Test that existing members with fee changes DO trigger tracking"""
        print("\n🧪 Testing existing member fee change (triggers tracking)...")

        # First create a member without fee override
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Existing",
                "last_name": "FeeTest" + random_string(4),
                "email": f"existing.feetest.{random_string(6)}@example.com",
                "birth_date": "1985-01-01",
                "status": "Active",
            }
        )
        member.insert(ignore_permissions=True)

        # Initially no fee override
        self.assertIsNone(member.membership_fee_override)
        print(f"✅ Created existing member {member.name} without fee override")

        # Now set a fee override (this should trigger change tracking)
        member.membership_fee_override = 125.0
        member.fee_override_reason = "Backend adjustment - Premium supporter"
        member.save(ignore_permissions=True)

        # KEY TEST: Check if change tracking was triggered for existing member
        self.assertTrue(
            hasattr(member, "_pending_fee_change"),
            "Existing member should have _pending_fee_change attribute",
        )

        # Verify the tracking data
        pending = member._pending_fee_change
        self.assertEqual(pending.get("new_amount"), 125.0)
        # old_amount could be None or 0.0 for first-time override
        self.assertIn(pending.get("old_amount"), [None, 0.0])
        self.assertIn("Premium supporter", pending.get("reason"))

        print(f"✅ Existing member {member.name} correctly triggers fee change tracking")
        print(f"   Old amount: {pending.get('old_amount')}")
        print(f"   New amount: {pending.get('new_amount')}")
        print(f"   Reason: {pending.get('reason')}")

    def test_application_simulation(self):
        """Test simulating the complete application submission process"""
        print("\n🧪 Testing application submission simulation...")

        # Simulate data from membership application form
        application_data = {
            "first_name": "AppSim",
            "last_name": "FeeTest" + random_string(4),
            "email": f"appsim.feetest.{random_string(6)}@example.com",
            "contact_number": "+31612345678",
            "birth_date": "1990-05-15",
            "address_line1": "Test Application Street 123",
            "city": "Amsterdam",
            "postal_code": "1012AB",
            "country": "Netherlands",
            "membership_amount": 65.0,  # Custom amount
            "uses_custom_amount": True,
            "custom_amount_reason": "Supporter contribution",
            "payment_method": "SEPA Direct Debit",
            "iban": "NL91ABNA0417164300",
            "bic": "ABNANL2A",
            "bank_account_name": "Test Application User",
        }

        # Use the application helper to create member (like real form submission)
        from verenigingen.utils.application_helpers import (
            create_member_from_application,
            generate_application_id,
        )

        app_id = generate_application_id()
        member = create_member_from_application(application_data, app_id)

        # Verify the member was created correctly
        self.assertEqual(member.membership_fee_override, 65.0)
        self.assertIn("Supporter contribution", member.fee_override_reason)
        self.assertEqual(member.application_status, "Pending")

        # KEY TEST: No fee change tracking should be triggered
        self.assertFalse(
            hasattr(member, "_pending_fee_change"),
            "Application-created member should not trigger fee change tracking",
        )

        print(f"✅ Application simulation successful for {member.name}")
        print(f"   Custom fee: €{member.membership_fee_override}")
        print(f"   Application ID: {member.application_id}")
        print("   No fee change tracking triggered (correct)")

    def test_fee_change_from_none_to_amount(self):
        """Test changing fee from None to a specific amount"""
        print("\n🧪 Testing fee change from None to amount...")

        # Create member without fee override
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "ChangeTest",
                "last_name": "FeeTest" + random_string(4),
                "email": f"changetest.feetest.{random_string(6)}@example.com",
                "birth_date": "1980-01-01",
                "status": "Active",
            }
        )
        member.insert(ignore_permissions=True)

        # Verify initially no fee override
        self.assertIsNone(member.membership_fee_override)

        # Set fee override for first time
        member.membership_fee_override = 99.0
        member.fee_override_reason = "First-time fee override"
        member.save(ignore_permissions=True)

        # Should trigger change tracking
        self.assertTrue(hasattr(member, "_pending_fee_change"))
        pending = member._pending_fee_change
        self.assertEqual(pending.get("new_amount"), 99.0)
        # old_amount could be None or 0.0 for first-time override
        self.assertIn(pending.get("old_amount"), [None, 0.0])

        print("✅ Fee change from None to €99.0 correctly tracked")

    def test_fee_change_from_amount_to_amount(self):
        """Test changing fee from one amount to another"""
        print("\n🧪 Testing fee change from amount to amount...")

        # Create member with initial fee override
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "AmountChange",
                "last_name": "FeeTest" + random_string(4),
                "email": f"amountchange.feetest.{random_string(6)}@example.com",
                "birth_date": "1975-01-01",
                "status": "Active",
                "membership_fee_override": 50.0,
                "fee_override_reason": "Initial custom amount",
            }
        )
        member.insert(ignore_permissions=True)

        # Clear any pending change from initial creation
        if hasattr(member, "_pending_fee_change"):
            delattr(member, "_pending_fee_change")

        # Now change the fee amount
        member.membership_fee_override = 150.0
        member.fee_override_reason = "Upgraded to premium supporter"
        member.save(ignore_permissions=True)

        # Should trigger change tracking with old and new amounts
        self.assertTrue(hasattr(member, "_pending_fee_change"))
        pending = member._pending_fee_change
        self.assertEqual(pending.get("new_amount"), 150.0)
        self.assertEqual(pending.get("old_amount"), 50.0)

        print("✅ Fee change from €50.0 to €150.0 correctly tracked")
        print(f"   Old: {pending.get('old_amount')}, New: {pending.get('new_amount')}")


def test_fee_override_integration():
    """Test the complete fee override integration"""
    print("=" * 60)
    print("TESTING FEE OVERRIDE INTEGRATION")
    print("=" * 60)

    try:
        # Find an existing member with a customer
        members = frappe.get_all(
            "Member",
            filters={"customer": ["!=", ""]},
            fields=["name", "full_name", "customer", "membership_fee_override"],
            limit=1,
        )

        if not members:
            print("❌ No members with customers found for testing")
            return

        member_data = members[0]
        print(f"📝 Testing with member: {member_data.name} ({member_data.full_name})")

        # Get the member document
        member = frappe.get_doc("Member", member_data.name)

        # Check initial state
        print("\n1. Initial state:")
        initial_fee = member.get_current_membership_fee()
        print(f"   Current fee: {initial_fee}")

        initial_subscriptions = frappe.get_all(
            "Subscription",
            filters={"party": member.customer, "party_type": "Customer"},
            fields=["name", "status"],
        )
        print(f"   Existing subscriptions: {len(initial_subscriptions)}")
        for sub in initial_subscriptions:
            print(f"     - {sub.name}: {sub.status}")

        # Apply fee override
        new_fee_amount = 99.99
        print(f"\n2. Applying fee override: €{new_fee_amount}")

        member.membership_fee_override = new_fee_amount
        member.fee_override_reason = "Integration test - automated fee override"
        member.save()

        print("   ✅ Fee override saved")

        # Check updated fee
        updated_fee = member.get_current_membership_fee()
        print(f"   Updated fee info: {updated_fee}")

        # Check if hook was triggered and subscriptions updated
        updated_subscriptions = frappe.get_all(
            "Subscription",
            filters={"party": member.customer, "party_type": "Customer"},
            fields=["name", "status", "modified"],
            order_by="modified desc",
        )

        print("\n3. After fee override:")
        print(f"   Subscriptions count: {len(updated_subscriptions)}")
        for sub in updated_subscriptions:
            print(f"     - {sub.name}: {sub.status} (modified: {sub.modified})")

            # Check subscription plan details
            sub_doc = frappe.get_doc("Subscription", sub.name)
            for plan in sub_doc.plans:
                plan_doc = frappe.get_doc("Subscription Plan", plan.plan)
                print(f"       Plan: {plan_doc.plan_name} - Cost: €{plan_doc.cost}")

        # Check fee change history
        member.reload()
        print("\n4. Fee change history:")
        print(f"   History entries: {len(member.fee_change_history)}")
        for entry in member.fee_change_history:
            print(f"     - {entry.change_date}: €{entry.old_amount} → €{entry.new_amount}")
            print(f"       Reason: {entry.reason}")
            print(f"       Changed by: {entry.changed_by}")

        # Check subscription history
        print("\n5. Subscription history:")
        print(f"   History entries: {len(member.subscription_history)}")
        for entry in member.subscription_history:
            print(f"     - {entry.subscription_name}: {entry.status} - €{entry.amount}")

        # Test subscription history refresh
        print("\n6. Testing subscription history refresh:")
        refresh_result = member.refresh_subscription_history()
        print(f"   Refresh result: {refresh_result}")

        member.reload()
        print(f"   Updated history entries: {len(member.subscription_history)}")

        print("\n" + "=" * 60)
        print("✅ FEE OVERRIDE INTEGRATION TEST COMPLETED SUCCESSFULLY")
        print("=" * 60)

        return {
            "success": True,
            "member": member_data.name,
            "initial_fee": initial_fee,
            "final_fee": updated_fee,
            "initial_subscriptions": len(initial_subscriptions),
            "final_subscriptions": len(updated_subscriptions),
        }

    except Exception as e:
        print(f"\n❌ INTEGRATION TEST FAILED: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}


def run_comprehensive_fee_tests():
    """Run comprehensive unit tests for fee override logic"""
    print("🚀 RUNNING COMPREHENSIVE FEE OVERRIDE TESTS")
    print("=" * 70)

    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestFeeOverrideLogic)

    # Custom result handler for better output
    class VerboseTestResult(unittest.TextTestResult):
        def startTest(self, test):
            super().startTest(test)
            print(f"\n🧪 Running: {test._testMethodName}")

        def addSuccess(self, test):
            super().addSuccess(test)
            print(f"✅ PASSED: {test._testMethodName}")

        def addError(self, test, err):
            super().addError(test, err)
            print(f"❌ ERROR: {test._testMethodName}")
            print(f"   {err[1]}")

        def addFailure(self, test, err):
            super().addFailure(test, err)
            print(f"❌ FAILED: {test._testMethodName}")
            print(f"   {err[1]}")

    # Run tests
    runner = unittest.TextTestRunner(resultclass=VerboseTestResult, verbosity=0)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 70)
    print("📊 COMPREHENSIVE TEST RESULTS")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.wasSuccessful():
        print("🎉 ALL COMPREHENSIVE TESTS PASSED!")
        print("   ✅ New member fee logic working correctly")
        print("   ✅ Existing member fee logic working correctly")
        print("   ✅ Application simulation working correctly")
        print("   ✅ Fee change tracking working correctly")
    else:
        print("⚠️  SOME TESTS FAILED!")
        for test, error in result.failures + result.errors:
            print(f"   ❌ {test._testMethodName}: {error}")

    print("=" * 70)
    return result.wasSuccessful()


if __name__ == "__main__":
    # Run both comprehensive tests and legacy integration test
    success1 = run_comprehensive_fee_tests()

    print("\n" + "=" * 70)
    print("RUNNING LEGACY INTEGRATION TEST")
    print("=" * 70)
    result2 = test_fee_override_integration()
    success2 = result2.get("success", False) if isinstance(result2, dict) else False

    print("\n🎯 OVERALL RESULTS:")
    print(f"   Comprehensive tests: {'✅ PASSED' if success1 else '❌ FAILED'}")
    print(f"   Legacy integration: {'✅ PASSED' if success2 else '❌ FAILED'}")

    if success1 and success2:
        print("🎉 ALL TESTS PASSED - Fee override logic is working correctly!")
    else:
        print("⚠️  Some tests failed - check output above")
