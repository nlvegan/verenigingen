# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for DuplicateInvoiceDetector service.
Tests the critical financial logic for preventing duplicate invoice generation.

Uses Enhanced Test Factory for real database operations - no mocks.
"""

import unittest
from datetime import date, timedelta

import frappe
from frappe.utils import add_days, add_months

from verenigingen.services.billing.duplicate_invoice_detector import (
    DuplicateInvoiceDetectionResult,
    DuplicateInvoiceDetector,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDuplicateInvoiceDetectionResult(EnhancedTestCase):
    """Test the result object"""

    def test_result_to_dict(self):
        """Result object converts to dict correctly"""
        result = DuplicateInvoiceDetectionResult(
            can_generate=False, reason="Test reason", extra_data="test"
        )

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
            first_name="Test",
            last_name="Detector",
            birth_date="1990-01-01"
        )

        # Create customer for the member using Enhanced Test Factory
        # The member needs a customer for invoice operations
        self.customer_doc = frappe.new_doc("Customer")
        self.customer_doc.customer_name = f"{self.member.first_name} {self.member.last_name}"
        self.customer_doc.customer_type = "Individual"
        self.customer_doc.insert()

        # Link customer to member
        self.member.customer = self.customer_doc.name
        self.member.save()

        self.customer = self.member.customer

        # Create membership (which also creates dues schedule automatically)
        self.membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name="Regular Member"
        )

        # Get the automatically created dues schedule
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1
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
        invoice = self.create_test_sales_invoice(
            customer=self.customer,
            posting_date="2025-01-05"
        )
        # Set coverage dates directly on database
        frappe.db.set_value("Sales Invoice", invoice.name, {
            "custom_coverage_start_date": "2025-01-01",
            "custom_coverage_end_date": "2025-01-31"
        })
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
        invoice = self.create_test_sales_invoice(
            customer=self.customer,
            posting_date="2025-01-10"
        )
        frappe.db.set_value("Sales Invoice", invoice.name, {
            "custom_coverage_start_date": "2025-01-15",
            "custom_coverage_end_date": "2025-02-14"
        })
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
        invoice = self.create_test_sales_invoice(
            customer=self.customer,
            posting_date="2024-12-05"
        )
        frappe.db.set_value("Sales Invoice", invoice.name, {
            "custom_coverage_start_date": "2024-12-01",
            "custom_coverage_end_date": "2024-12-31"
        })
        invoice.reload()
        invoice.submit()

        # Try to create invoice for January (no overlap)
        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        self.assertTrue(result.can_generate)
        self.assertEqual("No duplicates found", result.reason)

    def test_gap_reset_logic(self):
        """Large gap (>30 days) triggers gap reset"""
        # Create invoice from 2 months ago (Nov 1-30)
        old_invoice = self.create_test_sales_invoice(
            customer=self.customer,
            posting_date="2024-11-05"
        )
        frappe.db.set_value("Sales Invoice", old_invoice.name, {
            "custom_coverage_start_date": "2024-11-01",
            "custom_coverage_end_date": "2024-11-30"
        })
        old_invoice.reload()
        old_invoice.submit()

        # Try to create invoice for January (>30 day gap from Nov 30)
        detector = DuplicateInvoiceDetector(self.schedule)
        result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

        self.assertTrue(result.can_generate)
        self.assertIn("gap reset", result.reason)
        self.assertTrue(result.metadata.get("gap_reset"))

    def test_fallback_detection_for_missing_coverage(self):
        """Fallback detection works for invoices with missing coverage dates"""
        # First, get the schedule's current coverage period to create realistic overlap
        # For rolling year Annual membership, we need to set last_invoice_date so derivation works correctly
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, {
            "last_invoice_date": "2024-12-31"  # Previous invoice ended Dec 31
        })
        self.schedule.reload()

        # Create invoice WITHOUT coverage dates (fallback scenario)
        # This simulates an old invoice before coverage dates were implemented
        # Posting date is Jan 5, and with last_invoice_date=Dec 31, derived coverage should be Jan 1 - Dec 31
        invoice = self.create_test_sales_invoice(
            customer=self.customer,
            posting_date="2025-01-05"
        )
        # Set schedule link, clear coverage dates, and ensure posting_date persists
        frappe.db.set_value("Sales Invoice", invoice.name, {
            "membership_dues_schedule_display": self.schedule.name,
            "custom_coverage_start_date": None,
            "custom_coverage_end_date": None,
            "posting_date": "2025-01-05"  # Explicitly set posting_date again
        })
        frappe.db.commit()  # Commit to ensure persistence
        invoice.reload()
        invoice.submit()

        # Also create a recent coverage invoice so fallback check runs
        recent_invoice = self.create_test_sales_invoice(
            customer=self.customer,
            posting_date="2024-12-05"
        )
        frappe.db.set_value("Sales Invoice", recent_invoice.name, {
            "custom_coverage_start_date": "2024-12-01",
            "custom_coverage_end_date": "2024-12-31"
        })
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
        invoice = self.create_test_sales_invoice(
            customer=self.customer,
            posting_date="2025-01-05"
        )
        # Set schedule link and clear coverage dates
        frappe.db.set_value("Sales Invoice", invoice.name, {
            "membership_dues_schedule_display": self.schedule.name,
            "custom_coverage_start_date": None,
            "custom_coverage_end_date": None,
            "posting_date": "2025-01-05"
        })
        frappe.db.commit()
        invoice.reload()
        invoice.submit()

        # NOW corrupt the posting_date to trigger derivation error
        # This bypasses validation since the invoice is already submitted
        frappe.db.sql("""
            UPDATE `tabSales Invoice`
            SET posting_date = NULL
            WHERE name = %s
        """, (invoice.name,))
        frappe.db.commit()

        # Create recent coverage so fallback runs
        recent_invoice = self.create_test_sales_invoice(
            customer=self.customer,
            posting_date="2024-12-05"
        )
        frappe.db.set_value("Sales Invoice", recent_invoice.name, {
            "custom_coverage_start_date": "2024-12-01",
            "custom_coverage_end_date": "2024-12-31"
        })
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
        invoice1 = self.create_test_sales_invoice(
            customer=self.customer,
            posting_date="2025-01-05"
        )
        frappe.db.set_value("Sales Invoice", invoice1.name, {
            "custom_coverage_start_date": "2025-01-01",
            "custom_coverage_end_date": "2025-01-31"
        })
        invoice1.reload()
        invoice1.submit()

        invoice2 = self.create_test_sales_invoice(
            customer=self.customer,
            posting_date="2025-01-06"
        )
        frappe.db.set_value("Sales Invoice", invoice2.name, {
            "custom_coverage_start_date": "2025-01-01",
            "custom_coverage_end_date": "2025-01-31"
        })
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
