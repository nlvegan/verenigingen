"""
MemberPaymentMatcher Unit Test Suite

Tests the centralized member-payment matching logic used by both
payment retrieval modes for consistent bookkeeping.

Test Categories:
1. Customer ID Matching - Primary lookup path
2. Description Parsing - Fallback pattern matching
3. Member Status Inclusion - All statuses for bookkeeping
4. Singleton Behavior - Cache management
"""

from unittest.mock import MagicMock

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher import (
    MemberPaymentMatcher,
    get_member_payment_matcher,
    reset_member_payment_matcher,
)


class TestMemberPaymentMatcher(EnhancedTestCase):
    """Unit tests for MemberPaymentMatcher."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        # Reset singleton between tests
        reset_member_payment_matcher()

    def tearDown(self):
        """Clean up after tests."""
        reset_member_payment_matcher()
        super().tearDown()

    # =========================================================================
    # 1. Customer ID Matching Tests
    # =========================================================================

    def test_finds_member_by_customer_id(self):
        """Test that members are found by their Mollie customer_id."""
        # Create test member with Mollie customer ID
        member = self._create_test_member_with_mollie_id("cst_test123")

        matcher = MemberPaymentMatcher()

        # Mock payment object
        payment = MagicMock()
        payment.customer_id = "cst_test123"
        payment.description = ""

        result = matcher.find_member_for_payment(payment)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], member.name)

    def test_no_match_for_unknown_customer_id(self):
        """Test that unknown customer_ids return None."""
        matcher = MemberPaymentMatcher()

        payment = MagicMock()
        payment.customer_id = "cst_nonexistent"
        payment.description = ""

        result = matcher.find_member_for_payment(payment)

        self.assertIsNone(result)

    # =========================================================================
    # 2. Description Parsing Tests
    # =========================================================================

    def test_finds_member_by_description_pattern(self):
        """Test fallback matching via member ID in description."""
        # Create test member
        member = self.create_test_member()

        matcher = MemberPaymentMatcher()

        # Payment without customer_id but with member ID in description
        payment = MagicMock()
        payment.customer_id = None
        payment.description = f"Membership dues {member.name}"

        result = matcher.find_member_for_payment(payment)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], member.name)

    def test_description_pattern_requires_valid_member(self):
        """Test that description parsing only matches existing members."""
        matcher = MemberPaymentMatcher()

        payment = MagicMock()
        payment.customer_id = None
        payment.description = "Payment for Assoc-Member-9999-99-9999"

        result = matcher.find_member_for_payment(payment)

        self.assertIsNone(result)

    def test_description_parsing_extracts_correct_pattern(self):
        """Test the member ID regex pattern extraction."""
        member = self.create_test_member()

        matcher = MemberPaymentMatcher()

        # Various description formats
        test_cases = [
            f"Contributie {member.name}",
            f"Donation from {member.name} - thanks!",
            f"{member.name}",
            f"Invoice #{member.name}-001",
        ]

        for description in test_cases:
            with self.subTest(description=description):
                payment = MagicMock()
                payment.customer_id = None
                payment.description = description

                result = matcher.find_member_for_payment(payment)
                self.assertIsNotNone(result, f"Should match: {description}")
                self.assertEqual(result["name"], member.name)

    # =========================================================================
    # 3. Member Status Inclusion Tests (Critical for Bookkeeping)
    # =========================================================================

    def test_includes_terminated_members(self):
        """Test that Terminated members are included for bookkeeping."""
        member = self._create_test_member_with_mollie_id(
            "cst_terminated", status="Quit"
        )

        matcher = MemberPaymentMatcher()

        payment = MagicMock()
        payment.customer_id = "cst_terminated"
        payment.description = ""

        result = matcher.find_member_for_payment(payment)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], member.name)
        self.assertEqual(result["status"], "Quit")

    def test_includes_deceased_members(self):
        """Test that Deceased members are included for bookkeeping."""
        member = self._create_test_member_with_mollie_id(
            "cst_deceased", status="Deceased"
        )

        matcher = MemberPaymentMatcher()

        payment = MagicMock()
        payment.customer_id = "cst_deceased"
        payment.description = ""

        result = matcher.find_member_for_payment(payment)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], member.name)
        self.assertEqual(result["status"], "Deceased")

    def test_includes_banned_members(self):
        """Test that Banned members are included for bookkeeping."""
        member = self._create_test_member_with_mollie_id("cst_banned", status="Banned")

        matcher = MemberPaymentMatcher()

        payment = MagicMock()
        payment.customer_id = "cst_banned"
        payment.description = ""

        result = matcher.find_member_for_payment(payment)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], member.name)
        self.assertEqual(result["status"], "Banned")

    def test_all_members_list_includes_all_statuses(self):
        """Test that get_all_members_with_mollie_id returns all statuses."""
        # Create members with different statuses
        active = self._create_test_member_with_mollie_id("cst_active1", status="Active")
        terminated = self._create_test_member_with_mollie_id(
            "cst_term1", status="Quit"
        )

        matcher = MemberPaymentMatcher()
        all_members = matcher.get_all_members_with_mollie_id()

        member_names = [m["name"] for m in all_members]

        self.assertIn(active.name, member_names)
        self.assertIn(terminated.name, member_names)

    # =========================================================================
    # 4. Subscription ID NOT Used (By Design)
    # =========================================================================

    def test_does_not_match_by_subscription_id(self):
        """Test that subscription_id is NOT used for matching.

        Subscription IDs change over time, so historical payments would
        have outdated subscription IDs that no longer match.
        """
        # Create member with subscription ID
        member = self._create_test_member_with_mollie_id("cst_sub_test")
        member.mollie_subscription_id = "sub_test123"
        member.save()

        matcher = MemberPaymentMatcher()

        # Payment with only subscription_id (no customer_id)
        payment = MagicMock()
        payment.customer_id = None  # No customer ID
        payment.subscription_id = "sub_test123"
        payment.description = ""

        result = matcher.find_member_for_payment(payment)

        # Should NOT find member by subscription_id alone
        self.assertIsNone(result)

    # =========================================================================
    # 5. Singleton and Cache Tests
    # =========================================================================

    def test_singleton_returns_same_instance(self):
        """Test that get_member_payment_matcher returns singleton."""
        matcher1 = get_member_payment_matcher()
        matcher2 = get_member_payment_matcher()

        self.assertIs(matcher1, matcher2)

    def test_reset_clears_singleton(self):
        """Test that reset_member_payment_matcher clears the cache."""
        matcher1 = get_member_payment_matcher()
        reset_member_payment_matcher()
        matcher2 = get_member_payment_matcher()

        self.assertIsNot(matcher1, matcher2)

    def test_matcher_reset_clears_internal_cache(self):
        """Test that matcher.reset() clears loaded data."""
        matcher = MemberPaymentMatcher()

        # Force load
        matcher.get_member_count()
        self.assertTrue(matcher._loaded)

        # Reset
        matcher.reset()
        self.assertFalse(matcher._loaded)
        self.assertEqual(len(matcher._customer_id_map), 0)

    # =========================================================================
    # 6. Convenience Methods
    # =========================================================================

    def test_find_member_name_for_payment(self):
        """Test the convenience method that returns just the name."""
        member = self._create_test_member_with_mollie_id("cst_name_test")

        matcher = MemberPaymentMatcher()

        payment = MagicMock()
        payment.customer_id = "cst_name_test"
        payment.description = ""

        result = matcher.find_member_name_for_payment(payment)

        self.assertEqual(result, member.name)

    def test_is_customer_id_known(self):
        """Test the customer ID existence check."""
        self._create_test_member_with_mollie_id("cst_known")

        matcher = MemberPaymentMatcher()

        self.assertTrue(matcher.is_customer_id_known("cst_known"))
        self.assertFalse(matcher.is_customer_id_known("cst_unknown"))

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _create_test_member_with_mollie_id(self, customer_id, status="Active"):
        """Create a test member with Mollie customer ID."""
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": f"Test{frappe.generate_hash(length=6)}",
                "last_name": "MatcherTest",
                "email": f"test{frappe.generate_hash(length=6)}@example.com",
                "status": status,
                "mollie_customer_id": customer_id,
            }
        )
        member.insert(ignore_permissions=True)
        return member
