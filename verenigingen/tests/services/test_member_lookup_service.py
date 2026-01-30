# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Tests for MemberLookupService - cascade member matching.

This test module verifies the reusable member lookup service that provides
configurable cascade matching strategies for import operations.
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberLookupService(EnhancedTestCase):
    """Test cases for MemberLookupService."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

        from verenigingen.services.member.member_lookup_service import (
            MemberLookupService,
        )

        self.service = MemberLookupService()

        # Create test member using EnhancedTestCase factory method
        self.test_member = self.create_test_member(
            first_name="Lookup",
            last_name="Test",
            email="lookup-test@example.com",
        )
        # Set member_id after creation (not part of standard factory)
        self.test_member.db_set("member_id", "LOOKUP-123")
        frappe.db.commit()
        self.test_member.reload()

    def test_find_by_member_id(self):
        """Test finding member by member_id."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"member_id": "LOOKUP-123"},
            strategies=[LookupStrategy.MEMBER_ID],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_find_by_email_fallback(self):
        """Test finding member by email when member_id not found."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"member_id": "NONEXISTENT", "email": "lookup-test@example.com"},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_returns_none_when_not_found(self):
        """Test that None is returned when member not found."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"member_id": "NONEXISTENT", "email": "nonexistent@example.com"},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )
        self.assertIsNone(result)

    def test_default_strategies_used(self):
        """Test that VIP_STRATEGIES are used by default."""
        result = self.service.find_member(
            {"member_id": "LOOKUP-123"},
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_cascade_order_respected(self):
        """Test that cascade order is respected - first match wins."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        # Create a second member with different member_id but unique email
        second_member = self.create_test_member(
            first_name="Second",
            last_name="Member",
            email="second-lookup-test@example.com",
        )
        second_member.db_set("member_id", "LOOKUP-456")
        frappe.db.commit()
        second_member.reload()

        # When searching by member_id first, should find second_member
        result = self.service.find_member(
            {"member_id": "LOOKUP-456", "email": "second-lookup-test@example.com"},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )
        self.assertEqual(result.name, second_member.name)

        # When member_id doesn't match, should fall back to email
        result_email_fallback = self.service.find_member(
            {"member_id": "NONEXISTENT", "email": "second-lookup-test@example.com"},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result_email_fallback)
        self.assertEqual(result_email_fallback.name, second_member.name)

    def test_procurios_id_lookup(self):
        """Test finding member by procurios_id (stored in member_id field)."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"procurios_id": "LOOKUP-123"},
            strategies=[LookupStrategy.PROCURIOS_ID],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_personal_email_lookup(self):
        """Test finding member by personal_email."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"personal_email": "lookup-test@example.com"},
            strategies=[LookupStrategy.PERSONAL_EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_organization_email_lookup(self):
        """Test finding member by organization_email."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"organization_email": "lookup-test@example.com"},
            strategies=[LookupStrategy.ORGANIZATION_EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_mijnrood_strategies(self):
        """Test the MIJNROOD_STRATEGIES predefined strategy set."""
        result = self.service.find_member(
            {"member_id": "LOOKUP-123"},
            strategies=self.service.MIJNROOD_STRATEGIES,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_vip_strategies(self):
        """Test the VIP_STRATEGIES predefined strategy set."""
        result = self.service.find_member(
            {"personal_email": "lookup-test@example.com"},
            strategies=self.service.VIP_STRATEGIES,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_empty_row_data(self):
        """Test that empty row data returns None."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )
        self.assertIsNone(result)

    def test_none_values_in_row_data(self):
        """Test that None values in row data are handled gracefully."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"member_id": None, "email": None},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )
        self.assertIsNone(result)

    def test_singleton_accessor(self):
        """Test that get_member_lookup_service returns singleton."""
        from verenigingen.services.member.member_lookup_service import (
            get_member_lookup_service,
        )

        service1 = get_member_lookup_service()
        service2 = get_member_lookup_service()
        self.assertIs(service1, service2)

    # -------------------------------------------------------------------------
    # Email Normalization Tests (Code Review Requirement)
    # -------------------------------------------------------------------------

    def test_email_normalization_lowercase(self):
        """Test that email lookup works with uppercase input."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        # Search with uppercase email - should still find the member
        result = self.service.find_member(
            {"email": "LOOKUP-TEST@EXAMPLE.COM"},
            strategies=[LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_email_normalization_mixed_case(self):
        """Test that email lookup works with mixed case input."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"email": "LookUp-TeSt@ExAmPlE.cOm"},
            strategies=[LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_email_normalization_trailing_whitespace(self):
        """Test that email lookup works with trailing whitespace."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"email": "  lookup-test@example.com  "},
            strategies=[LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_email_normalization_leading_whitespace(self):
        """Test that email lookup works with leading whitespace."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"email": "   lookup-test@example.com"},
            strategies=[LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_email_normalization_combined(self):
        """Test that email lookup handles combined case and whitespace issues."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"email": "  LOOKUP-TEST@EXAMPLE.COM  "},
            strategies=[LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_email_normalization_empty_after_strip(self):
        """Test that whitespace-only email returns None."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"email": "   "},
            strategies=[LookupStrategy.EMAIL],
        )
        self.assertIsNone(result)

    # -------------------------------------------------------------------------
    # find_member_with_strategy Tests (Code Review Requirement)
    # -------------------------------------------------------------------------

    def test_find_member_with_strategy_returns_tuple(self):
        """Test that find_member_with_strategy returns (member, strategy) tuple."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        member, strategy = self.service.find_member_with_strategy(
            {"member_id": "LOOKUP-123"},
            strategies=[LookupStrategy.MEMBER_ID],
        )
        self.assertIsNotNone(member)
        self.assertEqual(member.name, self.test_member.name)
        self.assertEqual(strategy, LookupStrategy.MEMBER_ID)

    def test_find_member_with_strategy_fallback(self):
        """Test that find_member_with_strategy returns correct fallback strategy."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        # member_id won't match, should fall back to email
        member, strategy = self.service.find_member_with_strategy(
            {"member_id": "NONEXISTENT", "email": "lookup-test@example.com"},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(member)
        self.assertEqual(member.name, self.test_member.name)
        self.assertEqual(strategy, LookupStrategy.EMAIL)

    def test_find_member_with_strategy_not_found(self):
        """Test that find_member_with_strategy returns (None, None) when not found."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        member, strategy = self.service.find_member_with_strategy(
            {"member_id": "NONEXISTENT", "email": "nonexistent@example.com"},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )
        self.assertIsNone(member)
        self.assertIsNone(strategy)
