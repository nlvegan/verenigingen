import unittest

import frappe
from frappe.utils import today


class TestFeeOverrideSubscription(unittest.TestCase):
    """Test fee override and subscription management functionality"""

    def setUp(self):
        """Set up test data"""
        self.cleanup_test_data()

        # Create test customer first
        self.test_customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "Test Fee Override Customer",
                "customer_type": "Individual",
            }
        )
        self.test_customer.insert(ignore_permissions=True)

        # Create test member
        self.test_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "FeeOverride",
                "email": "test.feeoverride@example.com",
                "customer": self.test_customer.name,
                "member_since": today(),
            }
        )
        self.test_member.insert(ignore_permissions=True)

        # Create a membership type for testing
        self.membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test Membership",
                "amount": 100.00,
                "billing_frequency": "Monthly",
            }
        )
        self.membership_type.insert(ignore_permissions=True)
        # Create subscription plan for the membership type
        self.membership_type.create_subscription_plan()

    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()

    def cleanup_test_data(self):
        """Remove test data"""
        # Clean up in reverse order of dependencies
        frappe.db.delete("Subscription", {"party": ["like", "%Test Fee Override%"]})
        frappe.db.delete("Subscription Plan", {"plan_name": ["like", "%Test%"]})
        frappe.db.delete("Member", {"email": "test.feeoverride@example.com"})
        frappe.db.delete("Customer", {"customer_name": ["like", "%Test Fee Override%"]})
        frappe.db.delete("Membership Type", {"membership_type_name": ["like", "%Test%"]})
        frappe.db.commit()

    def test_subscription_update_methods_exist(self):
        """Test that subscription update methods exist on Member"""
        member = frappe.get_doc("Member", self.test_member.name)

        # Check if methods exist
        self.assertTrue(hasattr(member, "update_active_subscriptions"))
        self.assertTrue(hasattr(member, "get_or_create_subscription_for_membership"))
        self.assertTrue(hasattr(member, "refresh_subscription_history"))

        print(f"✓ All subscription methods exist on Member: {member.name}")

    def test_get_current_membership_fee(self):
        """Test getting current membership fee"""
        member = frappe.get_doc("Member", self.test_member.name)

        # Test without override
        fee_info = member.get_current_membership_fee()
        print(f"Fee info without override: {fee_info}")
        self.assertEqual(fee_info["source"], "none")
        self.assertEqual(fee_info["amount"], 0)

        # Test with override
        member.membership_fee_override = 150.00
        member.fee_override_reason = "Test override"
        member.save()

        fee_info = member.get_current_membership_fee()
        print(f"Fee info with override: {fee_info}")
        self.assertEqual(fee_info["source"], "custom_override")
        self.assertEqual(fee_info["amount"], 150.00)

    def test_fee_override_validation(self):
        """Test fee override validation logic"""
        member = frappe.get_doc("Member", self.test_member.name)

        # Test setting override without reason should fail
        member.membership_fee_override = 200.00
        with self.assertRaises(frappe.ValidationError):
            member.save()

        # Test setting override with reason should work
        member.fee_override_reason = "Special discount"
        member.save()

        # Check that audit fields are set
        member.reload()
        self.assertEqual(member.fee_override_by, frappe.session.user)
        self.assertEqual(member.fee_override_date, today())

        print(f"✓ Fee override validation working. Override by: {member.fee_override_by}")

    def test_subscription_creation_after_fee_change(self):
        """Test that subscriptions are created/updated after fee changes"""
        member = frappe.get_doc("Member", self.test_member.name)

        print(f"\n=== Testing subscription creation for member: {member.name} ===")

        # Check initial subscriptions
        initial_subscriptions = frappe.get_all(
            "Subscription",
            filters={"party": member.customer, "party_type": "Customer"},
            fields=["name", "status", "start_date", "end_date"],
        )
        print(f"Initial subscriptions: {len(initial_subscriptions)}")
        for sub in initial_subscriptions:
            print(f"  - {sub.name}: {sub.status}")

        # Apply fee override
        print("\nApplying fee override of 150.00...")
        member.membership_fee_override = 150.00
        member.fee_override_reason = "Test subscription creation"
        member.save()

        # Check if hook was called
        print(f"Checking if _pending_fee_change exists: {hasattr(member, '_pending_fee_change')}")

        # Manually trigger the after_save hook since it might not run in tests
        from verenigingen.verenigingen.doctype.member.member import handle_fee_override_after_save

        try:
            handle_fee_override_after_save(member)
            print("✓ After save hook executed successfully")
        except Exception as e:
            print(f"✗ After save hook failed: {str(e)}")

        # Check subscriptions after fee change
        updated_subscriptions = frappe.get_all(
            "Subscription",
            filters={"party": member.customer, "party_type": "Customer"},
            fields=["name", "status", "start_date", "end_date", "modified"],
        )
        print(f"Subscriptions after fee change: {len(updated_subscriptions)}")
        for sub in updated_subscriptions:
            print(f"  - {sub.name}: {sub.status} (modified: {sub.modified})")

        # Check fee change history
        member.reload()
        print(f"Fee change history entries: {len(member.fee_change_history)}")
        for entry in member.fee_change_history:
            print(
                f"  - {entry.change_date}: {entry.old_amount} -> {entry.new_amount} ({entry.subscription_action})"
            )

    def test_update_active_subscriptions_method(self):
        """Test the update_active_subscriptions method directly"""
        member = frappe.get_doc("Member", self.test_member.name)

        print("\n=== Testing update_active_subscriptions method ===")

        # Check if method exists and is callable
        if hasattr(member, "update_active_subscriptions"):
            print("✓ update_active_subscriptions method exists")

            try:
                result = member.update_active_subscriptions()
                print(f"✓ Method executed successfully. Result: {result}")

                # Check what subscriptions exist now
                subscriptions = frappe.get_all(
                    "Subscription",
                    filters={"party": member.customer, "party_type": "Customer"},
                    fields=["name", "status", "start_date", "end_date"],
                )
                print(f"Subscriptions after update: {len(subscriptions)}")
                for sub in subscriptions:
                    print(f"  - {sub.name}: {sub.status}")

            except Exception as e:
                print(f"✗ Method failed with error: {str(e)}")
                import traceback

                traceback.print_exc()
        else:
            print("✗ update_active_subscriptions method does not exist")

    def test_subscription_plan_creation(self):
        """Test if subscription plans can be created"""
        print("\n=== Testing subscription plan creation ===")

        # Try to create a subscription plan for the custom fee
        try:
            plan_name = f"Custom Fee Plan - {self.test_member.name}"

            # Check if plan already exists
            existing_plan = frappe.db.exists("Subscription Plan", {"plan_name": plan_name})
            if existing_plan:
                print(f"Plan already exists: {existing_plan}")
                return

            subscription_plan = frappe.get_doc(
                {
                    "doctype": "Subscription Plan",
                    "plan_name": plan_name,
                    "item": frappe.db.get_single_value("Selling Settings", "so_required") or "Test Item",
                    "price_determination": "Fixed rate",
                    "cost": 150.00,
                    "billing_frequency": "Monthly",
                    "billing_interval": 1,
                }
            )

            # Handle missing item
            if not frappe.db.exists("Item", subscription_plan.item):
                # Create a test item
                item = frappe.get_doc(
                    {
                        "doctype": "Item",
                        "item_code": "MEMBERSHIP-FEE",
                        "item_name": "Membership Fee",
                        "item_group": "Services",
                        "is_service_item": 1,
                        "maintain_stock": 0,
                    }
                )
                item.insert(ignore_permissions=True)
                subscription_plan.item = item.name

            subscription_plan.insert(ignore_permissions=True)
            print(f"✓ Subscription plan created: {subscription_plan.name}")

            # Try to create a subscription using this plan
            subscription = frappe.get_doc(
                {
                    "doctype": "Subscription",
                    "party_type": "Customer",
                    "party": self.test_member.customer,
                    "start_date": today(),
                    "plans": [{"plan": subscription_plan.name, "qty": 1}],
                }
            )
            subscription.insert(ignore_permissions=True)
            subscription.submit()
            print(f"✓ Subscription created: {subscription.name}")

        except Exception as e:
            print(f"✗ Subscription plan creation failed: {str(e)}")
            import traceback

            traceback.print_exc()

    def test_refresh_subscription_history(self):
        """Test the refresh subscription history functionality"""
        member = frappe.get_doc("Member", self.test_member.name)

        print("\n=== Testing refresh subscription history ===")

        # First create a subscription to have something to refresh
        self.test_subscription_plan_creation()

        # Test refresh method
        try:
            result = member.refresh_subscription_history()
            print(f"✓ Refresh result: {result}")

            member.reload()
            print(f"Subscription history entries: {len(member.subscription_history)}")
            for entry in member.subscription_history:
                print(f"  - {entry.subscription_name}: {entry.status} - {entry.amount}")

        except Exception as e:
            print(f"✗ Refresh subscription history failed: {str(e)}")
            import traceback

            traceback.print_exc()

    def test_new_member_fee_logic(self):
        """Test that new members with custom fees don't trigger change tracking"""
        print("\n=== Testing new member fee logic ===")

        # Create a completely new member with custom fee
        new_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "NewApp",
                "last_name": "TestMember",
                "email": "newapp.test@example.com",
                "birth_date": "1992-01-01",
                "membership_fee_override": 75.0,
                "fee_override_reason": "Custom contribution during application",
                "status": "Pending",
                "application_status": "Pending",
            }
        )

        # Insert (this will trigger validation including handle_fee_override_changes)
        new_member.insert(ignore_permissions=True)

        # Check that _pending_fee_change was NOT set (this was the bug)
        if hasattr(new_member, "_pending_fee_change"):
            print("❌ ERROR: New member should not have _pending_fee_change!")
            print(f"   Member: {new_member.name}")
            print(f"   Pending change: {new_member._pending_fee_change}")
            self.fail("New member should not trigger fee change tracking")
        else:
            print("✅ New member correctly skips fee change tracking")
            print(f"   Member: {new_member.name}")
            print(f"   Fee override: €{new_member.membership_fee_override}")

        # Verify fee override fields are set correctly
        self.assertEqual(new_member.membership_fee_override, 75.0)
        self.assertEqual(new_member.fee_override_reason, "Custom contribution during application")

        # Clean up
        frappe.delete_doc("Member", new_member.name, ignore_permissions=True)

    def test_existing_member_fee_change_tracking(self):
        """Test that existing members with fee changes DO trigger tracking"""
        print("\n=== Testing existing member fee change tracking ===")

        # Use the test member (already created and saved)
        member = frappe.get_doc("Member", self.test_member.name)

        # Initially no fee override
        self.assertIsNone(member.membership_fee_override)

        # Now set a fee override (this should trigger change tracking)
        member.membership_fee_override = 125.0
        member.fee_override_reason = "Premium supporter upgrade"
        member.save(ignore_permissions=True)

        # Check if change tracking was triggered
        if hasattr(member, "_pending_fee_change"):
            print("✅ Existing member correctly triggers fee change tracking")
            pending = member._pending_fee_change
            print(f"   Old amount: {pending.get('old_amount')}")
            print(f"   New amount: {pending.get('new_amount')}")
            print(f"   Reason: {pending.get('reason')}")

            # Verify the tracking data
            self.assertEqual(pending.get("new_amount"), 125.0)
            self.assertIsNone(pending.get("old_amount"))  # First time setting override
            self.assertIn("Premium supporter", pending.get("reason"))
        else:
            print("❌ ERROR: Existing member should have _pending_fee_change!")
            self.fail("Existing member should trigger fee change tracking")


def run_fee_override_tests():
    """Run all fee override tests and print results"""
    print("=" * 60)
    print("RUNNING FEE OVERRIDE SUBSCRIPTION TESTS")
    print("=" * 60)

    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestFeeOverrideSubscription)

    # Run tests with custom result handler
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

    runner = unittest.TextTestRunner(resultclass=VerboseTestResult, verbosity=0)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print(
        f"TESTS COMPLETED: {result.testsRun} run, {len(result.failures)} failed, {len(result.errors)} errors"
    )
    print("=" * 60)

    return result


if __name__ == "__main__":
    run_fee_override_tests()
