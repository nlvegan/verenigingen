# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Tests for MemberLookupService - cascade member matching.

This test module verifies the reusable member lookup service that provides
configurable cascade matching strategies for import operations.
"""

import time

import frappe
from frappe.tests.utils import FrappeTestCase


class TestMemberLookupService(FrappeTestCase):
    """Test cases for MemberLookupService."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

        from verenigingen.services.member.member_lookup_service import (
            MemberLookupService,
        )

        self.service = MemberLookupService()

        # Create test member with unique identifiers
        self.unique_suffix = str(int(time.time() * 1000))
        self.test_email = f"lookup-test-{self.unique_suffix}@example.com"
        self.test_member_id = f"LOOKUP-{self.unique_suffix}"

        self.test_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Lookup",
                "last_name": "Test",
                "email": self.test_email,
                "member_id": self.test_member_id,
                "status": "Pending",
            }
        )
        self.test_member.flags.ignore_validate = True
        self.test_member.flags.ignore_mandatory = True
        self.test_member.insert()
        frappe.db.commit()

    def tearDown(self):
        """Clean up test fixtures."""
        try:
            if self.test_member and frappe.db.exists("Member", self.test_member.name):
                frappe.delete_doc("Member", self.test_member.name, force=True)
                frappe.db.commit()
        except Exception:
            pass
        super().tearDown()

    def test_find_by_member_id(self):
        """Test finding member by member_id."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"member_id": self.test_member_id},
            strategies=[LookupStrategy.MEMBER_ID],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_find_by_email_fallback(self):
        """Test finding member by email when member_id not found."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"member_id": "NONEXISTENT", "email": self.test_email},
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
            {"member_id": self.test_member_id},
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_procurios_id_lookup(self):
        """Test finding member by procurios_id (stored in member_id field)."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"procurios_id": self.test_member_id},
            strategies=[LookupStrategy.PROCURIOS_ID],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_personal_email_lookup(self):
        """Test finding member by personal_email."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"personal_email": self.test_email},
            strategies=[LookupStrategy.PERSONAL_EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_organization_email_lookup(self):
        """Test finding member by organization_email."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"organization_email": self.test_email},
            strategies=[LookupStrategy.ORGANIZATION_EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_mijnrood_strategies(self):
        """Test the MIJNROOD_STRATEGIES predefined strategy set."""
        result = self.service.find_member(
            {"member_id": self.test_member_id},
            strategies=self.service.MIJNROOD_STRATEGIES,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_vip_strategies(self):
        """Test the VIP_STRATEGIES predefined strategy set."""
        result = self.service.find_member(
            {"personal_email": self.test_email},
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
            {"email": self.test_email.upper()},
            strategies=[LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_email_normalization_mixed_case(self):
        """Test that email lookup works with mixed case input."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        # Create mixed case version of email
        mixed_email = "".join(
            c.upper() if i % 2 else c.lower() for i, c in enumerate(self.test_email)
        )
        result = self.service.find_member(
            {"email": mixed_email},
            strategies=[LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_email_normalization_trailing_whitespace(self):
        """Test that email lookup works with trailing whitespace."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"email": f"  {self.test_email}  "},
            strategies=[LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_email_normalization_leading_whitespace(self):
        """Test that email lookup works with leading whitespace."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"email": f"   {self.test_email}"},
            strategies=[LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_email_normalization_combined(self):
        """Test that email lookup handles combined case and whitespace issues."""
        from verenigingen.services.member.member_lookup_service import LookupStrategy

        result = self.service.find_member(
            {"email": f"  {self.test_email.upper()}  "},
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
            {"member_id": self.test_member_id},
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
            {"member_id": "NONEXISTENT", "email": self.test_email},
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
