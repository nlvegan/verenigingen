"""
Unit tests for per-membership-type minimum period enforcement
"""

import unittest

import frappe
from frappe.utils import add_months, getdate, today

from .test_data_factory import TestDataFactory
from .test_membership_utilities import MembershipTestUtilities


class TestMembershipTypeMinimumPeriod(unittest.TestCase):
    """Test cases for the per-membership-type enforce_minimum_period setting"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        cls.factory = TestDataFactory()

    def setUp(self):
        """Set up before each test"""
        frappe.db.rollback()
        frappe.set_user("Administrator")

        # Create test data
        self.chapter = self.factory.create_test_chapters(count=1)[0]
        self.member = self.factory.create_test_members([self.chapter], count=1)[0]

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.rollback()

    def test_field_exists(self):
        """Test that the enforce_minimum_period field exists in Membership Type"""
        meta = frappe.get_meta("Membership Type")
        field_names = [f.fieldname for f in meta.fields]
        self.assertIn("enforce_minimum_period", field_names)

        # Check field properties
        field = meta.get_field("enforce_minimum_period")
        self.assertEqual(field.fieldtype, "Check")
        self.assertEqual(field.default, "1")

    def test_default_is_enforced(self):
        """Test that enforcement is enabled by default for new membership types"""
        mt = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test Default Enforcement",
                "amount": 100.0,
                "currency": "EUR",
                "subscription_period": "Monthly",
                "is_active": 1,
            }
        )
        mt.insert(ignore_permissions=True)

        # Default should be 1 (enforced)
        self.assertEqual(mt.enforce_minimum_period, 1)

    def test_renewal_with_enforcement(self):
        """Test renewal dates when enforcement is enabled"""
        # Create membership type with enforcement
        mt = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Enforced Monthly", period="Monthly", amount=25.0, enforce_minimum_period=True
        )["membership_type"]

        # Create membership
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": mt.name,
                "start_date": today(),
            }
        )
        membership.insert()

        # Should get 1 year renewal despite being monthly
        expected_renewal = add_months(getdate(today()), 12)
        self.assertEqual(getdate(membership.renewal_date), expected_renewal)

    def test_renewal_without_enforcement(self):
        """Test renewal dates when enforcement is disabled"""
        # Create membership type without enforcement
        mt = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Non-Enforced Monthly", period="Monthly", amount=25.0, enforce_minimum_period=False
        )["membership_type"]

        # Create membership
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": mt.name,
                "start_date": today(),
            }
        )
        membership.insert()

        # Should get actual monthly renewal (30 days)
        expected_renewal = add_months(getdate(today()), 1)
        self.assertEqual(getdate(membership.renewal_date), expected_renewal)

    def test_daily_membership_with_enforcement(self):
        """Test daily membership with enforcement gets 1 year"""
        mt = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Enforced Daily", period="Daily", amount=5.0, enforce_minimum_period=True
        )["membership_type"]

        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": mt.name,
                "start_date": today(),
            }
        )
        membership.insert()

        # Daily with enforcement should still get 1 year
        expected_renewal = add_months(getdate(today()), 12)
        self.assertEqual(getdate(membership.renewal_date), expected_renewal)

    def test_daily_membership_without_enforcement(self):
        """Test daily membership without enforcement gets 1 day"""
        mt = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Non-Enforced Daily", period="Daily", amount=5.0, enforce_minimum_period=False
        )["membership_type"]

        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": mt.name,
                "start_date": today(),
            }
        )
        membership.insert()

        # Daily without enforcement should get 1 day renewal
        from frappe.utils import add_days

        expected_renewal = add_days(getdate(today()), 1)
        self.assertEqual(getdate(membership.renewal_date), expected_renewal)

    def test_annual_membership_unaffected(self):
        """Test that annual memberships are unaffected by the setting"""
        # Test with enforcement enabled
        mt_enforced = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Enforced Annual", period="Annual", amount=100.0, enforce_minimum_period=True
        )["membership_type"]

        membership1 = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": mt_enforced.name,
                "start_date": today(),
            }
        )
        membership1.insert()

        # Test with enforcement disabled
        member2 = self.factory.create_test_members([self.chapter], count=1)[0]
        mt_not_enforced = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Non-Enforced Annual", period="Annual", amount=100.0, enforce_minimum_period=False
        )["membership_type"]

        membership2 = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member2.name,
                "membership_type": mt_not_enforced.name,
                "start_date": today(),
            }
        )
        membership2.insert()

        # Both should have 1 year renewal
        expected_renewal = add_months(getdate(today()), 12)
        self.assertEqual(getdate(membership1.renewal_date), expected_renewal)
        self.assertEqual(getdate(membership2.renewal_date), expected_renewal)

    def test_lifetime_membership_behavior(self):
        """Test lifetime membership behavior with and without enforcement"""
        # With enforcement
        mt_enforced = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Enforced Lifetime", period="Lifetime", amount=1000.0, enforce_minimum_period=True
        )["membership_type"]

        membership1 = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": mt_enforced.name,
                "start_date": today(),
            }
        )
        membership1.insert()

        # With enforcement, lifetime gets 1 year initial period
        expected_enforced = add_months(getdate(today()), 12)
        self.assertEqual(getdate(membership1.renewal_date), expected_enforced)

        # Without enforcement
        member2 = self.factory.create_test_members([self.chapter], count=1)[0]
        mt_not_enforced = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Non-Enforced Lifetime", period="Lifetime", amount=1000.0, enforce_minimum_period=False
        )["membership_type"]

        membership2 = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member2.name,
                "membership_type": mt_not_enforced.name,
                "start_date": today(),
            }
        )
        membership2.insert()

        # Without enforcement, lifetime gets 50 years
        from frappe.utils import add_years

        expected_not_enforced = add_years(getdate(today()), 50)
        self.assertEqual(getdate(membership2.renewal_date), expected_not_enforced)

    def test_context_manager_with_type_names(self):
        """Test the context manager with specific type names"""
        # Create two membership types
        mt1 = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Type 1", period="Monthly", amount=10.0, enforce_minimum_period=True
        )["membership_type"]

        mt2 = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Type 2", period="Monthly", amount=20.0, enforce_minimum_period=True
        )["membership_type"]

        # Both should have enforcement enabled
        self.assertEqual(mt1.enforce_minimum_period, 1)
        self.assertEqual(mt2.enforce_minimum_period, 1)

        # Use context manager to disable only for mt1
        with MembershipTestUtilities.with_minimum_period_disabled([mt1.name]):
            # Reload to check current values
            mt1_temp = frappe.get_doc("Membership Type", mt1.name)
            mt2_temp = frappe.get_doc("Membership Type", mt2.name)

            self.assertEqual(mt1_temp.enforce_minimum_period, 0)
            self.assertEqual(mt2_temp.enforce_minimum_period, 1)  # Should remain enabled

        # After context, both should be back to original
        mt1_after = frappe.get_doc("Membership Type", mt1.name)
        mt2_after = frappe.get_doc("Membership Type", mt2.name)

        self.assertEqual(mt1_after.enforce_minimum_period, 1)
        self.assertEqual(mt2_after.enforce_minimum_period, 1)

    def test_cancellation_validation_with_enforcement(self):
        """Test that cancellation validation respects per-type enforcement"""
        # Create membership type with enforcement
        mt = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Cancel Enforced", period="Monthly", amount=50.0, enforce_minimum_period=True
        )["membership_type"]

        # Create and submit membership
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": mt.name,
                "start_date": today(),
            }
        )
        membership.insert()
        membership.submit()

        # Try to cancel early as non-admin
        frappe.set_user("test@example.com")

        # Use cancel_membership function
        from verenigingen.verenigingen.doctype.membership.membership import cancel_membership

        with self.assertRaises(frappe.ValidationError) as cm:
            cancel_membership(membership.name, add_months(today(), 3), "Early cancellation")

        self.assertIn("1 year", str(cm.exception))

        frappe.set_user("Administrator")

    def test_cancellation_allowed_without_enforcement(self):
        """Test that cancellation is allowed when enforcement is disabled"""
        # Create membership type without enforcement
        mt = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Cancel Not Enforced", period="Monthly", amount=50.0, enforce_minimum_period=False
        )["membership_type"]

        # Create and submit membership
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": mt.name,
                "start_date": today(),
            }
        )
        membership.insert()
        membership.submit()

        # Should be able to cancel early
        from verenigingen.verenigingen.doctype.membership.membership import cancel_membership

        result = cancel_membership(membership.name, add_months(today(), 3), "Early cancellation allowed")
        self.assertEqual(result, membership.name)

        # Verify cancellation was set
        membership.reload()
        self.assertIsNotNone(membership.cancellation_date)
        self.assertEqual(membership.cancellation_reason, "Early cancellation allowed")
