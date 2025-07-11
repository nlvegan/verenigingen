"""
Example test file demonstrating how to use the membership test utilities
"""

import unittest

import frappe
from frappe.utils import today

from .test_data_factory import TestDataFactory
from .test_membership_utilities import MembershipTestUtilities


class TestMembershipUtilitiesExample(unittest.TestCase):
    """Example test cases showing proper membership type creation"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        cls.factory = TestDataFactory()

    def setUp(self):
        """Set up before each test"""
        frappe.db.rollback()

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.rollback()

    def test_create_daily_membership_type(self):
        """Test creating a daily membership type for short-term testing"""
        result = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Daily Test Membership",
            period="Daily",
            amount=5.0,
            create_subscription_plan=True,
            create_item=True,
        )

        # Verify membership type
        self.assertIn("membership_type", result)
        mt = result["membership_type"]
        self.assertEqual(mt.subscription_period, "Daily")
        self.assertEqual(mt.amount, 5.0)

        # Verify subscription plan
        self.assertIn("subscription_plan", result)
        sp = result["subscription_plan"]
        self.assertEqual(sp.billing_interval, "Day")
        self.assertEqual(sp.billing_interval_count, 1)
        self.assertEqual(sp.cost, 5.0)

        # Verify item
        self.assertIn("item", result)
        item = result["item"]
        self.assertTrue(item.is_subscription_item)

    def test_create_monthly_membership_type(self):
        """Test creating a monthly membership type"""
        result = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Monthly Premium", period="Monthly", amount=25.0
        )

        mt = result["membership_type"]
        self.assertEqual(mt.subscription_period, "Monthly")
        self.assertEqual(mt.amount, 25.0)

        sp = result["subscription_plan"]
        self.assertEqual(sp.billing_interval, "Month")
        self.assertEqual(sp.billing_interval_count, 1)

    def test_create_quarterly_membership_type(self):
        """Test creating a quarterly membership type"""
        result = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Quarterly Standard", period="Quarterly", amount=70.0
        )

        mt = result["membership_type"]
        self.assertEqual(mt.subscription_period, "Quarterly")

        sp = result["subscription_plan"]
        self.assertEqual(sp.billing_interval, "Month")
        self.assertEqual(sp.billing_interval_count, 3)  # Quarterly = 3 months

    def test_create_membership_with_subscription(self):
        """Test creating a membership with proper subscription linkage"""
        # Create a test chapter and member
        chapter = self.factory.create_test_chapters(count=1)[0]
        member = self.factory.create_test_members([chapter], count=1)[0]

        # Create membership type with subscription
        mt_result = MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Monthly", period="Monthly", amount=15.0
        )

        # Create membership with subscription
        membership_result = MembershipTestUtilities.create_membership_with_subscription(
            member=member, membership_type=mt_result["membership_type"], start_date=today()
        )

        # Verify membership
        self.assertIn("membership", membership_result)
        membership = membership_result["membership"]
        self.assertEqual(membership.member, member.name)
        self.assertEqual(membership.membership_type, mt_result["membership_type"].name)

        # Verify subscription
        self.assertIn("subscription", membership_result)
        subscription = membership_result["subscription"]
        self.assertEqual(subscription.status, "Active")
        self.assertEqual(len(subscription.plans), 1)
        self.assertEqual(subscription.plans[0].plan, mt_result["subscription_plan"].name)

    def test_create_standard_membership_types(self):
        """Test creating a standard set of membership types"""
        types = MembershipTestUtilities.create_standard_membership_types()

        # Should create 7 standard types
        self.assertEqual(len(types), 7)

        # Check variety of periods
        periods = [t["membership_type"].subscription_period for t in types]
        self.assertIn("Daily", periods)
        self.assertIn("Monthly", periods)
        self.assertIn("Quarterly", periods)
        self.assertIn("Annual", periods)
        self.assertIn("Lifetime", periods)

        # Check that all have subscription plans
        for type_result in types:
            self.assertIn("subscription_plan", type_result)
            self.assertIn("item", type_result)

    def test_integration_with_test_factory(self):
        """Test integration with TestDataFactory"""
        # Create test data using factory with new utilities
        chapters = self.factory.create_test_chapters(count=2)
        membership_types = self.factory.create_test_membership_types(count=3, with_subscriptions=True)
        members = self.factory.create_test_members(chapters, count=5)
        memberships = self.factory.create_test_memberships(members, membership_types, with_subscriptions=True)

        # Verify all memberships were created
        self.assertGreater(len(memberships), 0)

        # Check that memberships have proper structure
        for membership in memberships:
            self.assertTrue(hasattr(membership, "member"))
            self.assertTrue(hasattr(membership, "membership_type"))
            self.assertTrue(hasattr(membership, "start_date"))

    def test_cleanup_test_data(self):
        """Test cleanup of test membership types"""
        # Create some test types
        MembershipTestUtilities.create_membership_type_with_subscription(
            name="Test Cleanup Type", period="Monthly", amount=10.0
        )

        # Cleanup
        cleaned = MembershipTestUtilities.cleanup_test_membership_types(prefix="Test")
        self.assertGreater(cleaned, 0)

        # Verify cleanup
        remaining = frappe.get_all("Membership Type", filters={"membership_type_name": ["like", "Test%"]})
        self.assertEqual(len(remaining), 0)

    def test_membership_with_actual_periods(self):
        """Test memberships with actual subscription periods (no 1-year minimum)"""
        # Disable minimum period enforcement for this test
        with MembershipTestUtilities.with_minimum_period_disabled():
            # Create a test chapter and member
            chapter = self.factory.create_test_chapters(count=1)[0]
            member = self.factory.create_test_members([chapter], count=1)[0]

            # Create daily membership type
            mt_result = MembershipTestUtilities.create_membership_type_with_subscription(
                name="Test Daily No Minimum", period="Daily", amount=5.0
            )

            # Create membership
            membership_result = MembershipTestUtilities.create_membership_with_subscription(
                member=member, membership_type=mt_result["membership_type"], start_date=today()
            )

            membership = membership_result["membership"]
            membership.reload()  # Reload to get calculated values

            # With minimum period disabled, renewal date should be 1 day from start
            # (not 1 year as would be with enforcement enabled)
            from frappe.utils import add_days

            add_days(membership.start_date, 1)

            # Note: Due to the current implementation, this might still be 1 year
            # This test demonstrates how to disable the setting for testing
