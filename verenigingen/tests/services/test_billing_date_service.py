# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for BillingDateService.

Tests date calculation and management functionality including:
- Next invoice date calculation for various billing frequencies
- Billing day initialization from member anniversary
- Schedule date advancement for retry logic
"""

from datetime import date
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.services.billing.billing_date_service import (
    BillingDateService,
    get_billing_date_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestBillingDateService(EnhancedTestCase):
    """Test suite for BillingDateService."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_billing_date_service()

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        service = BillingDateService()
        self.assertEqual(service.service_name, "BillingDateService")
        self.assertIsNotNone(service.logger)

    def test_get_billing_date_service_returns_instance(self):
        """Test that factory function returns service instance."""
        service = get_billing_date_service()
        self.assertIsInstance(service, BillingDateService)

    def test_calculate_next_invoice_date_monthly(self):
        """Test next invoice date calculation for monthly frequency."""
        mock_schedule = MagicMock()
        mock_schedule.billing_frequency = "Monthly"
        mock_schedule.next_invoice_date = "2025-01-15"

        next_date = self.service.calculate_next_invoice_date(mock_schedule)

        # Should be approximately one month later
        expected = getdate("2025-02-15")
        self.assertEqual(next_date, expected)

    def test_calculate_next_invoice_date_quarterly(self):
        """Test next invoice date calculation for quarterly frequency."""
        mock_schedule = MagicMock()
        mock_schedule.billing_frequency = "Quarterly"
        mock_schedule.next_invoice_date = "2025-01-15"

        next_date = self.service.calculate_next_invoice_date(mock_schedule)

        # Should be approximately three months later
        expected = getdate("2025-04-15")
        self.assertEqual(next_date, expected)

    def test_calculate_next_invoice_date_annual(self):
        """Test next invoice date calculation for annual frequency."""
        mock_schedule = MagicMock()
        mock_schedule.billing_frequency = "Annual"
        mock_schedule.next_invoice_date = "2025-01-15"

        next_date = self.service.calculate_next_invoice_date(mock_schedule)

        # Should be approximately one year later
        expected = getdate("2026-01-15")
        self.assertEqual(next_date, expected)

    def test_calculate_next_invoice_date_uses_today_when_no_date(self):
        """Test that calculation defaults to today when no next_invoice_date."""
        mock_schedule = MagicMock()
        mock_schedule.billing_frequency = "Monthly"
        mock_schedule.next_invoice_date = None

        next_date = self.service.calculate_next_invoice_date(mock_schedule)

        # Should be one month from today
        expected = add_months(getdate(today()), 1)
        self.assertEqual(next_date, expected)

    def test_calculate_next_invoice_date_with_from_date(self):
        """Test calculation with explicit from_date parameter."""
        mock_schedule = MagicMock()
        mock_schedule.billing_frequency = "Monthly"
        mock_schedule.next_invoice_date = "2025-01-01"  # Should be ignored

        next_date = self.service.calculate_next_invoice_date(
            mock_schedule, from_date="2025-03-15"
        )

        expected = getdate("2025-04-15")
        self.assertEqual(next_date, expected)


class TestBillingDateServiceSetBillingDay(EnhancedTestCase):
    """Test suite for set_billing_day functionality."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_billing_date_service()

    def test_set_billing_day_from_member_since(self):
        """Test that billing day is set from member's anniversary date."""
        # Create a test member with member_since date
        test_member = self.create_test_member(
            first_name="BillingDay",
            last_name="Test",
            email=f"billingday.test.{frappe.generate_hash(length=6)}@test.com",
        )
        test_member.member_since = "2023-03-15"  # 15th of the month
        test_member.save()

        mock_schedule = MagicMock()
        mock_schedule.billing_day = None
        mock_schedule.member = test_member.name

        self.service.set_billing_day(mock_schedule)

        self.assertEqual(mock_schedule.billing_day, 15)

    def test_set_billing_day_defaults_to_1_without_member_since(self):
        """Test that billing day defaults to 1 when member has no member_since date."""
        test_member = self.create_test_member(
            first_name="NoBillingDay",
            last_name="Test",
            email=f"nobillingday.test.{frappe.generate_hash(length=6)}@test.com",
        )
        test_member.member_since = None
        test_member.save()

        mock_schedule = MagicMock()
        mock_schedule.billing_day = None
        mock_schedule.member = test_member.name

        self.service.set_billing_day(mock_schedule)

        self.assertEqual(mock_schedule.billing_day, 1)

    def test_set_billing_day_defaults_to_1_for_templates(self):
        """Test that billing day defaults to 1 for templates without member."""
        mock_schedule = MagicMock()
        mock_schedule.billing_day = None
        mock_schedule.member = None

        self.service.set_billing_day(mock_schedule)

        self.assertEqual(mock_schedule.billing_day, 1)

    def test_set_billing_day_preserves_existing_value(self):
        """Test that existing billing_day is not overwritten."""
        mock_schedule = MagicMock()
        mock_schedule.billing_day = 20
        mock_schedule.member = "some-member"

        self.service.set_billing_day(mock_schedule)

        # Should preserve the existing value
        self.assertEqual(mock_schedule.billing_day, 20)

    def test_set_billing_day_replaces_zero(self):
        """Test that billing_day of 0 is treated as unset."""
        test_member = self.create_test_member(
            first_name="ZeroBillingDay",
            last_name="Test",
            email=f"zerobilling.test.{frappe.generate_hash(length=6)}@test.com",
        )
        test_member.member_since = "2023-07-25"  # 25th of the month
        test_member.save()

        mock_schedule = MagicMock()
        mock_schedule.billing_day = 0
        mock_schedule.member = test_member.name

        self.service.set_billing_day(mock_schedule)

        self.assertEqual(mock_schedule.billing_day, 25)
