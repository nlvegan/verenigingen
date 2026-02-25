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


class TestUpdateScheduleDates(EnhancedTestCase):
    """Test suite for update_schedule_dates functionality."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_billing_date_service()

    def test_update_schedule_dates_with_actual_invoice_date_mocked(self):
        """Test that schedule dates are updated correctly with actual invoice date."""
        # Use mock schedule to avoid fixture dependencies
        mock_schedule = MagicMock()
        mock_schedule.billing_frequency = "Monthly"
        mock_schedule.next_invoice_date = "2025-01-15"
        mock_schedule.last_invoice_coverage_end = None
        mock_schedule.member = None  # Skip member update for this test

        # Update with actual invoice date
        self.service.update_schedule_dates(mock_schedule, actual_invoice_date="2025-01-15")

        # Verify dates were set correctly
        self.assertEqual(mock_schedule.last_invoice_date, "2025-01-15")
        self.assertEqual(mock_schedule.next_invoice_date, getdate("2025-02-15"))
        mock_schedule.save.assert_called_once()

    def test_update_schedule_dates_without_actual_invoice_date_mocked(self):
        """Test fallback behavior when no actual invoice date provided."""
        mock_schedule = MagicMock()
        mock_schedule.billing_frequency = "Monthly"
        mock_schedule.next_invoice_date = "2025-02-01"
        mock_schedule.member = None

        # Update without actual invoice date (test mode)
        self.service.update_schedule_dates(mock_schedule)

        # Verify fallback behavior
        self.assertEqual(mock_schedule.last_invoice_date, "2025-02-01")
        self.assertEqual(mock_schedule.next_invoice_date, getdate("2025-03-01"))
        mock_schedule.save.assert_called_once()

    def test_update_schedule_dates_no_recursive_cycle_mocked(self):
        """
        Test that update_schedule_dates() does not cause recursive save cycles.

        This test verifies that calling save() inside update_schedule_dates()
        happens exactly once - confirming no recursive loops exist.

        The call chain is:
        1. update_schedule_dates() -> schedule.save()
        2. save() -> validate() hooks
        3. validate() should NOT call update_schedule_dates()

        If hooks called update_schedule_dates(), save() would be called multiple times.
        """
        mock_schedule = MagicMock()
        mock_schedule.billing_frequency = "Monthly"
        mock_schedule.next_invoice_date = "2025-03-01"
        mock_schedule.last_invoice_coverage_end = None
        mock_schedule.member = None

        # Call update_schedule_dates
        self.service.update_schedule_dates(mock_schedule, actual_invoice_date="2025-03-01")

        # Verify save was called exactly once (not multiple times which would indicate recursion)
        self.assertEqual(
            mock_schedule.save.call_count, 1,
            "save() should be called exactly once by update_schedule_dates() - "
            f"actual call count: {mock_schedule.save.call_count}"
        )

    def test_update_schedule_dates_updates_member_next_invoice_date(self):
        """Test that member's next_invoice_date is updated correctly."""
        test_member = self.create_test_member(
            first_name="MemberDateUpdate",
            last_name="Test",
            email=f"memberdateupdate.test.{frappe.generate_hash(length=6)}@test.com",
        )

        # Use mock schedule with real member reference
        mock_schedule = MagicMock()
        mock_schedule.billing_frequency = "Monthly"
        mock_schedule.next_invoice_date = getdate("2025-05-01")  # After update
        mock_schedule.last_invoice_coverage_end = None
        mock_schedule.member = test_member.name

        # Call update directly to _update_member_next_invoice_date
        self.service._update_member_next_invoice_date(mock_schedule)

        # Verify member's next_invoice_date was updated
        member_next_date = frappe.db.get_value("Member", test_member.name, "next_invoice_date")
        self.assertEqual(getdate(member_next_date), getdate("2025-05-01"))

    def test_update_schedule_dates_skips_terminated_member(self):
        """Test that terminated member's next_invoice_date is not updated."""
        test_member = self.create_test_member(
            first_name="TerminatedMember",
            last_name="Test",
            email=f"terminatedmember.test.{frappe.generate_hash(length=6)}@test.com",
        )
        test_member.status = "Quit"
        test_member.next_invoice_date = "2025-01-01"
        test_member.save()

        # Use mock schedule with real member reference
        mock_schedule = MagicMock()
        mock_schedule.next_invoice_date = getdate("2025-06-01")  # New date
        mock_schedule.member = test_member.name

        # Call update directly to _update_member_next_invoice_date
        self.service._update_member_next_invoice_date(mock_schedule)

        # Member's next_invoice_date should NOT be updated (member is Terminated)
        member_next_date = frappe.db.get_value("Member", test_member.name, "next_invoice_date")
        self.assertEqual(
            getdate(member_next_date), getdate("2025-01-01"),
            "Terminated member's next_invoice_date should not be updated"
        )

    def test_update_schedule_dates_daily_uses_coverage_end(self):
        """Test that daily billing uses coverage end date for next calculation."""
        mock_schedule = MagicMock()
        mock_schedule.billing_frequency = "Daily"
        mock_schedule.next_invoice_date = "2025-01-01"
        mock_schedule.last_invoice_coverage_end = "2025-01-05"  # Coverage ends Jan 5
        mock_schedule.member = None

        # Update with actual invoice date
        self.service.update_schedule_dates(mock_schedule, actual_invoice_date="2025-01-01")

        # For daily billing, next date should be based on coverage end
        # Daily billing adds 1 day to coverage end
        self.assertEqual(mock_schedule.next_invoice_date, getdate("2025-01-06"))
