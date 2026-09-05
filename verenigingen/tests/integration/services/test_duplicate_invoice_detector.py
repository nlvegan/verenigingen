# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for DuplicateInvoiceDetector service.
Tests the critical financial logic for preventing duplicate invoice generation.

Uses Enhanced Test Factory for real database operations - no mocks.
"""

from datetime import date

import frappe

from verenigingen.services.billing.duplicate_invoice_detector import (
    DuplicateInvoiceDetectionResult,
    DuplicateInvoiceDetector,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDuplicateInvoiceDetectionResult(EnhancedTestCase):
    """Test the result object"""

    def test_result_to_dict(self):
        """Result object converts to dict correctly"""
        result = DuplicateInvoiceDetectionResult(can_generate=False, reason="Test reason", extra_data="test")

        result_dict = result.to_dict()

        self.assertEqual(result_dict["can_generate"], False)
        self.assertEqual(result_dict["reason"], "Test reason")
        self.assertEqual(result_dict["extra_data"], "test")

    def test_result_repr(self):
        """Result object has useful repr"""
        result = DuplicateInvoiceDetectionResult(can_generate=True, reason="No duplicates")

        repr_str = repr(result)

        self.assertIn("can_generate=True", repr_str)
        self.assertIn("No duplicates", repr_str)


class TestDuplicateInvoiceDetector(EnhancedTestCase):
    """Test the DuplicateInvoiceDetector service with real database operations"""

    def setUp(self):
        """Set up test fixtures with real data"""
        super().setUp()

        # Create real test member with customer
        self.member = self.create_test_member(
            first_name="Test", last_name="Detector", birth_date="1990-01-01"
        )

        # Reuse the Customer auto-created by create_test_member. Creating a second
        # Customer with the same name collides on the Customer PRIMARY key
        # (DuplicateEntryError). link_member_to_customer is idempotent.
        self.customer_doc = self.link_member_to_customer(self.member)
        self.customer = self.member.customer

        # Create membership (which also creates dues schedule automatically)
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name="Regular Member"
        )

        # Get the automatically created dues schedule
        schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"member": self.member.name, "status": "Active"}, limit=1
        )
        if schedules:
            self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        else:
            frappe.throw("No schedule was created with membership")

        # Reload member to ensure we have latest data
        self.member.reload()

    def test_no_member_skips_check(self):
        """When schedule has no member, detection is skipped"""
        # Create schedule without member
        schedule_no_member = frappe.new_doc("Membership Dues Schedule")
        schedule_no_member.billing_frequency = "Monthly"
        schedule_no_member.member = None

        detector = DuplicateInvoiceDetector(schedule_no_member)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        self.assertTrue(result.can_generate)
        self.assertIn("No member", result.reason)

    def test_no_customer_skips_check(self):
        """When member has no customer, detection is skipped"""
        # Use existing schedule but clear the customer from the member
        # Save current customer
        original_customer = self.member.customer

        # Temporarily clear customer
        frappe.db.set_value("Member", self.member.name, "customer", None)
        frappe.db.commit()  # Ensure it's persisted

        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        # Restore customer for other tests
        frappe.db.set_value("Member", self.member.name, "customer", original_customer)
        frappe.db.commit()

        self.assertTrue(result.can_generate)
        self.assertIn("No customer", result.reason)

    def test_exact_duplicate_prevented(self):
        """Exact duplicate coverage period is prevented"""
        # Create real invoice with exact coverage period
        invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2025-01-05")
        # Set coverage dates directly on database
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {"custom_coverage_start_date": "2025-01-01", "custom_coverage_end_date": "2025-01-31"},
        )
        # Submit the invoice
        invoice.reload()
        invoice.submit()

        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        self.assertFalse(result.can_generate)
        self.assertIn("Duplicate coverage prevented", result.reason)
        self.assertIn(invoice.name, result.reason)

    def test_partial_overlap_prevented(self):
        """Partial overlap coverage period is prevented"""
        # Create invoice with partial overlap (Jan 15 - Feb 14)
        invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2025-01-10")
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {"custom_coverage_start_date": "2025-01-15", "custom_coverage_end_date": "2025-02-14"},
        )
        invoice.reload()
        invoice.submit()

        # Try to create invoice for Jan 1-31 (overlaps with Jan 15-31)
        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        self.assertFalse(result.can_generate)
        self.assertIn("Coverage overlap prevented", result.reason)
        self.assertIn(invoice.name, result.reason)

    def test_no_overlaps_allows_generation(self):
        """No overlapping invoices allows generation"""
        # Create invoice for previous month (Dec 1-31)
        invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2024-12-05")
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {"custom_coverage_start_date": "2024-12-01", "custom_coverage_end_date": "2024-12-31"},
        )
        invoice.reload()
        invoice.submit()

        # Try to create invoice for January (no overlap)
        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        self.assertTrue(result.can_generate)
        self.assertEqual("No duplicates found", result.reason)

    def test_gap_reset_logic(self):
        """Large gap (>1 billing period) triggers gap reset for a Monthly schedule.

        Pinned to Monthly explicitly: the gap-reset threshold now scales to the
        schedule's own billing_frequency (see test_gap_reset_scales_down_for_weekly_frequency),
        so this ~32-day gap only reads as "large" for a Monthly (or shorter) cadence -
        it would NOT trigger reset for the auto-created default schedule's real
        Annual frequency, where 32 days is well under one period.
        """
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, "billing_frequency", "Monthly")
        self.schedule.reload()

        # Create invoice from 2 months ago (Nov 1-30)
        old_invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2024-11-05")
        frappe.db.set_value(
            "Sales Invoice",
            old_invoice.name,
            {"custom_coverage_start_date": "2024-11-01", "custom_coverage_end_date": "2024-11-30"},
        )
        old_invoice.reload()
        old_invoice.submit()

        # Try to create invoice for January (>30 day gap from Nov 30)
        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        self.assertTrue(result.can_generate)
        self.assertIn("gap reset", result.reason)
        self.assertTrue(result.metadata.get("gap_reset"))

    def test_gap_reset_scales_down_for_weekly_frequency(self):
        """A Weekly schedule's gap-reset threshold must scale to ~1 Weekly period
        (7 days), not the flat 30-day threshold tuned for Monthly billing. A 14-day
        gap is under the old flat 30-day constant (so it would NOT have triggered
        gap reset), but it is two full Weekly periods overdue."""
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, "billing_frequency", "Weekly")
        self.schedule.reload()

        old_invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2025-01-05")
        frappe.db.set_value(
            "Sales Invoice",
            old_invoice.name,
            {"custom_coverage_start_date": "2025-01-01", "custom_coverage_end_date": "2025-01-07"},
        )
        old_invoice.reload()
        old_invoice.submit()

        # Proposed period starts 14 days after the last coverage end (Jan 7).
        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 21), date(2025, 1, 27))

        self.assertTrue(result.can_generate)
        self.assertIn("gap reset", result.reason)
        self.assertTrue(result.metadata.get("gap_reset"))

    def test_gap_reset_not_triggered_within_a_single_weekly_period(self):
        """A gap well inside one Weekly period must NOT trigger gap reset - the
        scaled-down threshold isn't simply "always reset for short frequencies"."""
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, "billing_frequency", "Weekly")
        self.schedule.reload()

        old_invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2025-01-05")
        frappe.db.set_value(
            "Sales Invoice",
            old_invoice.name,
            {"custom_coverage_start_date": "2025-01-01", "custom_coverage_end_date": "2025-01-07"},
        )
        old_invoice.reload()
        old_invoice.submit()

        # Proposed period starts 3 days after the last coverage end (Jan 7) - well
        # within one Weekly period.
        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 10), date(2025, 1, 16))

        self.assertTrue(result.can_generate)
        self.assertNotIn("gap reset", result.reason)
        self.assertFalse(result.metadata.get("gap_reset"))

    def test_gap_reset_not_triggered_for_annual_frequency_normal_gap(self):
        """Locks in the semantic change on the OTHER side of this fix: a ~32-day
        gap - previously treated as "large" for EVERY schedule under the old flat
        30-day constant - must no longer trigger gap reset for an Annual schedule,
        where 32 days is well under one 365-day period. Auto-created dues
        schedules default to Annual (see the membership type's template creation
        logic), so this is the common case, not an edge case. The gap is still
        resolved correctly (as "no duplicates found"), just via the ordinary
        overlap/fallback checks instead of a short-circuiting gap reset.
        """
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, "billing_frequency", "Annual")
        self.schedule.reload()

        # Same ~32-day gap as test_gap_reset_logic above (Nov 30 -> Jan 1), which
        # DID trigger gap reset for a Monthly schedule.
        old_invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2024-11-05")
        frappe.db.set_value(
            "Sales Invoice",
            old_invoice.name,
            {"custom_coverage_start_date": "2024-11-01", "custom_coverage_end_date": "2024-11-30"},
        )
        old_invoice.reload()
        old_invoice.submit()

        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        self.assertTrue(result.can_generate)
        self.assertNotIn("gap reset", result.reason)
        self.assertFalse(result.metadata.get("gap_reset"))

    def test_fallback_detection_for_missing_coverage(self):
        """Fallback detection works for invoices with missing coverage dates"""
        # First, get the schedule's current coverage period to create realistic overlap
        # For rolling year Annual membership, we need to set last_invoice_date so derivation works correctly
        frappe.db.set_value(
            "Membership Dues Schedule",
            self.schedule.name,
            {"last_invoice_date": "2024-12-31"},  # Previous invoice ended Dec 31
        )
        self.schedule.reload()

        # Create invoice WITHOUT coverage dates (fallback scenario)
        # This simulates an old invoice before coverage dates were implemented
        # Posting date is Jan 5, and with last_invoice_date=Dec 31, derived coverage should be Jan 1 - Dec 31
        invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2025-01-05")
        # Set schedule link, clear coverage dates, and ensure posting_date persists
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {
                "membership_dues_schedule_display": self.schedule.name,
                "custom_coverage_start_date": None,
                "custom_coverage_end_date": None,
                "posting_date": "2025-01-05",  # Explicitly set posting_date again
            },
        )
        frappe.db.commit()  # Commit to ensure persistence
        invoice.reload()
        invoice.submit()

        # Also create a recent coverage invoice so fallback check runs
        recent_invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2024-12-05")
        frappe.db.set_value(
            "Sales Invoice",
            recent_invoice.name,
            {"custom_coverage_start_date": "2024-12-01", "custom_coverage_end_date": "2024-12-31"},
        )
        recent_invoice.reload()
        recent_invoice.submit()

        # Try to create invoice for same period as fallback invoice
        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        # The fallback detection should catch the overlap via derived coverage
        self.assertFalse(result.can_generate)
        self.assertIn("fallback detection", result.reason)
        self.assertIn(invoice.name, result.reason)

    def test_fallback_handles_derivation_errors(self):
        """Fallback detection gracefully handles derivation errors"""
        # Create invoice with missing coverage dates
        invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2025-01-05")
        # Set schedule link and clear coverage dates
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {
                "membership_dues_schedule_display": self.schedule.name,
                "custom_coverage_start_date": None,
                "custom_coverage_end_date": None,
                "posting_date": "2025-01-05",
            },
        )
        frappe.db.commit()
        invoice.reload()
        invoice.submit()

        # NOW corrupt the posting_date to trigger derivation error
        # This bypasses validation since the invoice is already submitted
        frappe.db.sql(
            """
            UPDATE `tabSales Invoice`
            SET posting_date = NULL
            WHERE name = %s
        """,
            (invoice.name,),
        )
        frappe.db.commit()

        # Create recent coverage so fallback runs
        recent_invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2024-12-05")
        frappe.db.set_value(
            "Sales Invoice",
            recent_invoice.name,
            {"custom_coverage_start_date": "2024-12-01", "custom_coverage_end_date": "2024-12-31"},
        )
        recent_invoice.reload()
        recent_invoice.submit()

        # Should continue gracefully despite derivation error
        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        # Should allow generation since derivation failed
        self.assertTrue(result.can_generate)

    def test_multiple_exact_duplicates_listed(self):
        """Multiple exact duplicates are all listed in reason"""
        # Create two invoices with exact same coverage period
        invoice1 = self.create_test_sales_invoice(customer=self.customer, posting_date="2025-01-05")
        frappe.db.set_value(
            "Sales Invoice",
            invoice1.name,
            {"custom_coverage_start_date": "2025-01-01", "custom_coverage_end_date": "2025-01-31"},
        )
        invoice1.reload()
        invoice1.submit()

        invoice2 = self.create_test_sales_invoice(customer=self.customer, posting_date="2025-01-06")
        frappe.db.set_value(
            "Sales Invoice",
            invoice2.name,
            {"custom_coverage_start_date": "2025-01-01", "custom_coverage_end_date": "2025-01-31"},
        )
        invoice2.reload()
        invoice2.submit()

        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        self.assertFalse(result.can_generate)
        # Both invoices should be listed
        self.assertIn(invoice1.name, result.reason)
        self.assertIn(invoice2.name, result.reason)

    def test_detector_initialization(self):
        """Detector initializes with correct attributes"""
        detector = DuplicateInvoiceDetector(self.schedule)

        self.assertEqual(detector.schedule, self.schedule)
        self.assertEqual(detector.member, self.member.name)
        # Billing frequency comes from schedule (could be Annual/Monthly/etc)
        self.assertIsNotNone(detector.billing_frequency)

    def test_fallback_cutoff_first_time_uses_sentinel(self):
        """_get_fallback_cutoff_date returns the 1900-01-01 sentinel when the
        customer has NO submitted invoice carrying a coverage end date (first-time
        generation), so all missing-coverage invoices become eligible for the
        fallback overlap scan. Here we create a missing-coverage invoice that
        overlaps the proposed period and assert it is caught via that path."""
        from verenigingen.services.billing.duplicate_invoice_detector import FALLBACK_CUTOFF_DATE

        # No coverage-dated invoice exists -> cutoff must be the sentinel.
        detector = DuplicateInvoiceDetector(self.schedule)
        self.assertEqual(detector._get_fallback_cutoff_date(self.customer), FALLBACK_CUTOFF_DATE)

        # And an undated invoice posted after the sentinel is scanned by fallback.
        frappe.db.set_value(
            "Membership Dues Schedule", self.schedule.name, {"last_invoice_date": "2024-12-31"}
        )
        self.schedule.reload()
        invoice = self.create_test_sales_invoice(customer=self.customer, posting_date="2025-01-05")
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {
                "membership_dues_schedule_display": self.schedule.name,
                "custom_coverage_start_date": None,
                "custom_coverage_end_date": None,
                "posting_date": "2025-01-05",
            },
        )
        frappe.db.commit()
        invoice.reload()
        invoice.submit()

        result = DuplicateInvoiceDetector(self.schedule).check_for_duplicates(
            date(2025, 1, 1), date(2025, 1, 31)
        )
        self.assertFalse(result.can_generate)
        self.assertIn(invoice.name, result.reason)

    def test_gap_reset_skips_fallback_for_large_gap(self):
        """When the most recent coverage ended far in the past (> 1 billing period
        from the proposed start), gap-reset logic returns can_generate=True with the
        'gap reset applied' reason and the gap_reset metadata flag, short-circuiting
        fallback processing.

        Pinned to Monthly explicitly - see test_gap_reset_logic above for why the
        threshold is no longer a flat 30 days regardless of frequency.
        """
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, "billing_frequency", "Monthly")
        self.schedule.reload()

        # A coverage-dated invoice ending long ago.
        old = self.create_test_sales_invoice(customer=self.customer, posting_date="2024-01-05")
        frappe.db.set_value(
            "Sales Invoice",
            old.name,
            {"custom_coverage_start_date": "2024-01-01", "custom_coverage_end_date": "2024-01-31"},
        )
        old.reload()
        old.submit()

        detector = DuplicateInvoiceDetector(self.schedule)
        # Propose a period starting > 30 days after the last coverage end (Jan 31 2024).
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        self.assertTrue(result.can_generate)
        self.assertIn("gap reset", result.reason)
        self.assertTrue(result.metadata.get("gap_reset"))
