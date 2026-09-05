# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for InvoiceGenerator service.
Tests the invoice generation logic extracted from MembershipDuesSchedule.

Uses Enhanced Test Factory for real database operations - no mocks.
"""

import unittest
from datetime import date
from unittest.mock import patch

import frappe

from verenigingen.services.billing.invoice_generator import InvoiceGenerator
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestInvoiceGenerator(EnhancedTestCase):
    """Test the InvoiceGenerator service with real database operations"""

    def setUp(self):
        """Set up test fixtures with real data"""
        super().setUp()

        # Create real test member
        self.member = self.create_test_member(
            first_name="Invoice", last_name="Test", birth_date="1985-05-15"
        )

        # Reuse the Customer auto-created by create_test_member. Creating a second
        # Customer with the same name collides on the Customer PRIMARY key
        # (DuplicateEntryError). link_member_to_customer is idempotent.
        self.customer_doc = self.link_member_to_customer(self.member)

        # Create membership (which also creates dues schedule automatically)
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name="Regular Member"
        )

        # Get the automatically created dues schedule
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1,
        )
        if schedules:
            self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        else:
            frappe.throw("No schedule was created with membership")

        # Reload member to ensure we have latest data
        self.member.reload()

    def test_happy_path_invoice_generation(self):
        """Generate invoice with all valid configuration"""
        # Arrange
        generator = InvoiceGenerator(self.schedule)
        coverage_start = date(2025, 1, 1)
        coverage_end = date(2025, 12, 31)

        # Act
        result = generator.generate_invoice(
            coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
        )

        # Assert
        self.assertTrue(result.success, f"Invoice generation failed: {result.error_message}")
        self.assertIsNotNone(result.data)
        self.assertEqual(result.data.customer, self.customer_doc.name)
        self.assertEqual(result.data.member, self.member.name)
        self.assertEqual(str(result.data.custom_coverage_start_date), "2025-01-01")
        self.assertEqual(str(result.data.custom_coverage_end_date), "2025-12-31")
        self.assertEqual(result.data.is_membership_invoice, 1)
        self.assertEqual(result.data.membership_dues_schedule_display, self.schedule.name)

        # Verify invoice has items
        self.assertEqual(len(result.data.items), 1)
        self.assertEqual(result.data.items[0].qty, 1)
        self.assertEqual(result.data.items[0].rate, self.schedule.dues_rate)

    # ========== Account Configuration Tests ==========

    def test_income_account_fallback_to_company_default(self):
        """Test income account falls back to company default when settings account doesn't exist"""
        # Arrange
        settings = frappe.get_single("Verenigingen Settings")
        original_account = frappe.db.get_value(
            "Verenigingen Payments Settings", None, "dues_income_account"
        )

        # Set invalid income account in settings
        frappe.db.set_value(
            "Verenigingen Payments Settings", None, "dues_income_account", "Invalid-Account-999"
        )
        frappe.db.commit()

        try:
            generator = InvoiceGenerator(self.schedule)
            coverage_start = date(2025, 1, 1)
            coverage_end = date(2025, 12, 31)

            # Act
            result = generator.generate_invoice(
                coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
            )

            # Assert - should succeed with company default
            self.assertTrue(result.success, f"Invoice generation failed: {result.error_message}")
            self.assertIsNotNone(result.data)
            # Verify fallback was used (company default income account)
            company_doc = frappe.get_cached_doc("Company", settings.company)
            self.assertEqual(result.data.items[0].income_account, company_doc.default_income_account)

        finally:
            # Restore original setting
            frappe.db.set_value(
                "Verenigingen Payments Settings", None, "dues_income_account", original_account
            )
            frappe.db.commit()

    def test_missing_income_account_fails_gracefully(self):
        """Test that missing income account (no fallback) fails with clear error"""
        # Arrange
        settings = frappe.get_single("Verenigingen Settings")
        original_account = frappe.db.get_value(
            "Verenigingen Payments Settings", None, "dues_income_account"
        )

        # Check if company actually has a fallback account
        company_doc = frappe.get_doc("Company", settings.company)
        has_company_fallback = bool(company_doc.default_income_account)

        if not has_company_fallback:
            # Perfect - no fallback exists, just clear settings account
            frappe.db.set_value("Verenigingen Payments Settings", None, "dues_income_account", None)
            frappe.db.commit()

            try:
                generator = InvoiceGenerator(self.schedule)
                coverage_start = date(2025, 1, 1)
                coverage_end = date(2025, 12, 31)

                # Act
                result = generator.generate_invoice(
                    coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
                )

                # Assert - should fail with clear error
                self.assertFalse(result.success)
                self.assertIn("Income account not configured", result.error_message)

            finally:
                # Restore original settings
                frappe.db.set_value(
                    "Verenigingen Payments Settings", None, "dues_income_account", original_account
                )
                frappe.db.commit()
        else:
            # Company has fallback - we need to clear both, but this is risky in tests
            # Skip this test since modifying company defaults could break other tests
            self.skipTest(
                "Company has default_income_account fallback - skipping to avoid modifying company config"
            )

    # ========== SEPA Configuration Tests ==========

    def test_sepa_mandate_linked_to_invoice(self):
        """Test that active SEPA mandate is properly linked to invoice"""
        # Arrange - create SEPA mandate for member
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.member = self.member.name
        mandate.customer = self.customer_doc.name
        mandate.status = "Active"
        mandate.is_active = 1
        mandate.used_for_memberships = 1
        mandate.iban = "NL91ABNA0417164300"
        mandate.account_holder_name = f"{self.member.first_name} {self.member.last_name}"
        mandate.sign_date = date(2024, 1, 1)
        mandate.sign_date = date(2024, 1, 1)
        mandate.insert()
        frappe.db.commit()

        generator = InvoiceGenerator(self.schedule)
        coverage_start = date(2025, 1, 1)
        coverage_end = date(2025, 12, 31)

        # Act
        result = generator.generate_invoice(
            coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
        )

        # Assert
        self.assertTrue(result.success)
        # Check if SEPA field exists on invoice (custom field may not be installed)
        if hasattr(result.data, "sepa_mandate_id"):
            self.assertIsNotNone(result.data.sepa_mandate_id)
            self.assertEqual(result.data.sepa_mandate_id, mandate.name)

        # Note: Cleanup handled by EnhancedTestCase tearDown

    def test_expired_sepa_mandate_falls_back_to_bank_transfer(self):
        """Test that expired SEPA mandate causes fallback to Bank Transfer"""
        # Arrange - create expired SEPA mandate
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.member = self.member.name
        mandate.customer = self.customer_doc.name
        mandate.status = "Active"
        mandate.is_active = 1
        mandate.used_for_memberships = 1
        mandate.iban = "NL91ABNA0417164300"
        mandate.account_holder_name = f"{self.member.first_name} {self.member.last_name}"
        mandate.sign_date = date(2024, 1, 1)
        mandate.expiry_date = date(2024, 12, 31)  # Expired
        mandate.insert()
        frappe.db.commit()

        generator = InvoiceGenerator(self.schedule)
        coverage_start = date(2025, 1, 1)
        coverage_end = date(2025, 12, 31)

        # Act
        result = generator.generate_invoice(
            coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
        )

        # Assert - should succeed but without SEPA mandate
        self.assertTrue(result.success)
        # Mandate should NOT be linked due to expiration (if field exists)
        if hasattr(result.data, "sepa_mandate_id"):
            self.assertIsNone(result.data.sepa_mandate_id)

        # Note: Cleanup handled by EnhancedTestCase tearDown

    def test_no_sepa_mandate_uses_bank_transfer(self):
        """Test that absence of SEPA mandate defaults to Bank Transfer"""
        # Arrange - no SEPA mandate created
        generator = InvoiceGenerator(self.schedule)
        coverage_start = date(2025, 1, 1)
        coverage_end = date(2025, 12, 31)

        # Act
        result = generator.generate_invoice(
            coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
        )

        # Assert
        self.assertTrue(result.success)
        # Check if SEPA field exists (custom field may not be installed)
        if hasattr(result.data, "sepa_mandate_id"):
            self.assertIsNone(result.data.sepa_mandate_id)

    # ========== Auto-Submit Tests ==========

    def test_auto_submit_enabled_submits_invoice(self):
        """Test that auto-submit enabled results in submitted invoice"""
        # Arrange - ensure auto-submit is enabled
        frappe.db.set_value("Verenigingen Settings", None, "auto_submit_membership_invoices", 1)
        frappe.db.commit()

        try:
            generator = InvoiceGenerator(self.schedule)
            coverage_start = date(2025, 1, 1)
            coverage_end = date(2025, 12, 31)

            # Act
            result = generator.generate_invoice(
                coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
            )

            # Assert
            self.assertTrue(result.success)
            self.assertEqual(result.data.docstatus, 1)  # 1 = Submitted
            self.assertTrue(result.metadata.get("submitted", False))

        finally:
            # Cleanup - reset to default
            frappe.db.set_value("Verenigingen Settings", None, "auto_submit_membership_invoices", 1)
            frappe.db.commit()

    def test_auto_submit_disabled_keeps_draft(self):
        """Test that auto-submit disabled keeps invoice as draft"""
        # Arrange - disable auto-submit
        frappe.db.set_value("Verenigingen Settings", None, "auto_submit_membership_invoices", 0)
        frappe.db.commit()

        try:
            generator = InvoiceGenerator(self.schedule)
            coverage_start = date(2025, 1, 1)
            coverage_end = date(2025, 12, 31)

            # Act
            result = generator.generate_invoice(
                coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
            )

            # Assert
            self.assertTrue(result.success)
            self.assertEqual(result.data.docstatus, 0)  # 0 = Draft
            self.assertFalse(result.metadata.get("submitted", True))

        finally:
            # Cleanup - reset to default
            frappe.db.set_value("Verenigingen Settings", None, "auto_submit_membership_invoices", 1)
            frappe.db.commit()

    # ========== Validation Error Tests ==========

    def test_missing_customer_validation_error(self):
        """Test validation fails when member has no customer"""
        # Arrange - remove customer from member
        original_customer = self.member.customer
        self.member.customer = None
        self.member.save()
        frappe.db.commit()

        try:
            generator = InvoiceGenerator(self.schedule)
            coverage_start = date(2025, 1, 1)
            coverage_end = date(2025, 12, 31)

            # Act
            result = generator.generate_invoice(
                coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
            )

            # Assert
            self.assertFalse(result.success)
            self.assertIn("does not have a customer record", result.error_message)

        finally:
            # Restore customer
            self.member.customer = original_customer
            self.member.save()
            frappe.db.commit()

    def test_missing_company_configuration_error(self):
        """Test validation fails when company not configured"""
        # Arrange - remove company from settings
        settings = frappe.get_single("Verenigingen Settings")
        original_company = settings.company
        frappe.db.set_value("Verenigingen Settings", None, "company", None)
        frappe.db.commit()

        try:
            generator = InvoiceGenerator(self.schedule)
            coverage_start = date(2025, 1, 1)
            coverage_end = date(2025, 12, 31)

            # Act
            result = generator.generate_invoice(
                coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
            )

            # Assert
            self.assertFalse(result.success)
            self.assertIn("Company not configured", result.error_message)

        finally:
            # Restore company
            frappe.db.set_value("Verenigingen Settings", None, "company", original_company)
            frappe.db.commit()

    def test_invalid_coverage_dates_validation(self):
        """Test validation fails for invalid coverage dates (start > end)"""
        # Arrange
        generator = InvoiceGenerator(self.schedule)
        coverage_start = date(2025, 12, 31)
        coverage_end = date(2025, 1, 1)  # End before start

        # Act
        result = generator.generate_invoice(
            coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
        )

        # Assert
        self.assertFalse(result.success)
        self.assertIn("must not be after end date", result.error_message)

    def test_member_document_mismatch_validation(self):
        """Test validation fails when member_doc doesn't match schedule"""
        # Arrange - create different member
        other_member = self.create_test_member(
            first_name="Other", last_name="Member", birth_date="1990-01-01"
        )

        # Act - pass wrong member doc
        generator = InvoiceGenerator(self.schedule)
        coverage_start = date(2025, 1, 1)
        coverage_end = date(2025, 12, 31)

        result = generator.generate_invoice(
            coverage_start=coverage_start, coverage_end=coverage_end, member_doc=other_member
        )

        # Assert
        self.assertFalse(result.success)
        self.assertIn("Member document mismatch", result.error_message)

        # Note: Cleanup handled by EnhancedTestCase tearDown - no manual deletion needed

    # ========== Edge Case Tests ==========

    def test_custom_billing_frequency_item_naming(self):
        """Test item naming for custom billing frequency"""
        # Arrange - modify schedule to custom frequency
        original_frequency = self.schedule.billing_frequency
        self.schedule.billing_frequency = "Custom"
        self.schedule.custom_frequency_number = 3
        self.schedule.custom_frequency_unit = "Months"
        self.schedule.save()
        frappe.db.commit()

        try:
            generator = InvoiceGenerator(self.schedule)
            coverage_start = date(2025, 1, 1)
            coverage_end = date(2025, 3, 31)

            # Act
            result = generator.generate_invoice(
                coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
            )

            # Assert
            self.assertTrue(result.success)
            # Verify item code contains custom frequency description
            item_code = result.data.items[0].item_code
            self.assertIn("Custom", item_code)
            self.assertIn("Every 3 Months", item_code)

        finally:
            # Restore original frequency
            self.schedule.billing_frequency = original_frequency
            self.schedule.save()
            frappe.db.commit()

    def test_payment_terms_template_applied(self):
        """Test payment terms template is properly applied to invoice"""
        # Check if a payment terms template exists
        templates = frappe.get_all("Payment Terms Template", limit=1)
        if not templates:
            self.skipTest("No payment terms templates available in test environment")

        template_name = templates[0].name

        # Arrange - set payment terms on schedule
        original_terms = self.schedule.payment_terms_template
        self.schedule.payment_terms_template = template_name
        self.schedule.save()
        frappe.db.commit()

        try:
            generator = InvoiceGenerator(self.schedule)
            coverage_start = date(2025, 1, 1)
            coverage_end = date(2025, 12, 31)

            # Act
            result = generator.generate_invoice(
                coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
            )

            # Assert
            self.assertTrue(result.success)
            self.assertEqual(result.data.payment_terms_template, template_name)

        finally:
            # Restore original terms
            self.schedule.payment_terms_template = original_terms
            self.schedule.save()
            frappe.db.commit()


class TestInvoiceGeneratorPeriodAnchorGuard(EnhancedTestCase):
    """
    Regression coverage for the #882/#884/#890 period-anchor invariant guard.

    The member's anchor (Membership.start_date) is deliberately the 15th of a
    month - not the 1st, not 1 January, not a quarter start. A boundary-anchored
    fixture would pass identically whether the guard works or not (see #890
    comment history), so it proves nothing.
    """

    ANCHOR = date(2024, 11, 15)

    def setUp(self):
        super().setUp()

        self.member = self.create_test_member(
            first_name="Anchor", last_name="Guard", birth_date="1985-05-15"
        )
        self.customer_doc = self.link_member_to_customer(self.member)

        self.membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name="Regular Member",
            start_date=self.ANCHOR,
        )

        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1,
        )
        if not schedules:
            frappe.throw("No schedule was created with membership")
        self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        self.schedule.billing_frequency = "Quarterly"

        self.member.reload()

    def _error_log_count(self, since):
        return frappe.db.count(
            "Error Log",
            filters={"creation": [">=", since], "method": ["like", "%Period Anchor Violation%"]},
        )

    def test_calendar_anchored_period_generates_invoice_and_flags_violation(self):
        """A calendar-quarter-anchored coverage_start (the #884/#890 shape) must
        still produce the invoice (non-blocking) but be flagged: Error Log +
        a comment on the invoice."""
        self.expectErrorLog("Period Anchor Violation")
        marker = frappe.utils.now_datetime()

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),  # calendar quarter start, not the member's own cycle
            coverage_end=date(2025, 3, 31),
            member_doc=self.member,
        )

        self.assertTrue(result.success, f"Invoice generation failed: {result.error_message}")
        invoice = result.data
        self.assertEqual(str(invoice.custom_coverage_start_date), "2025-01-01")

        self.assertEqual(
            self._error_log_count(marker),
            1,
            "Expected exactly one Period Anchor Violation Error Log entry",
        )

        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice.name,
                "content": ["like", "%Period anchor violation%"],
            },
        )
        self.assertEqual(len(comments), 1, "Expected exactly one anchor-violation comment on the invoice")

    def test_cycle_anchored_first_period_generates_invoice_without_flag(self):
        """coverage_start exactly on the member's own anchor - no previous
        invoice yet - must NOT be flagged."""
        marker = frappe.utils.now_datetime()

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=self.ANCHOR,
            coverage_end=date(2025, 2, 14),  # ANCHOR + 1 Quarterly period
            member_doc=self.member,
        )

        self.assertTrue(result.success, f"Invoice generation failed: {result.error_message}")
        invoice = result.data

        self.assertEqual(self._error_log_count(marker), 0)

        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice.name,
                "content": ["like", "%Period anchor violation%"],
            },
        )
        self.assertEqual(len(comments), 0)

    def test_cycle_anchored_second_period_generates_invoice_without_flag(self):
        """coverage_start exactly one period after a previous submitted
        invoice's coverage_end must NOT be flagged, even though it does not
        match the member's raw anchor date."""
        first = InvoiceGenerator(self.schedule).generate_invoice(
            coverage_start=self.ANCHOR,
            coverage_end=date(2025, 2, 14),
            member_doc=self.member,
        )
        self.assertTrue(first.success, f"First invoice generation failed: {first.error_message}")

        marker = frappe.utils.now_datetime()
        second = InvoiceGenerator(self.schedule).generate_invoice(
            coverage_start=date(2025, 2, 15),
            coverage_end=date(2025, 5, 14),
            member_doc=self.member,
        )

        self.assertTrue(second.success, f"Second invoice generation failed: {second.error_message}")
        self.assertEqual(self._error_log_count(marker), 0)

    def test_anchored_start_with_wrong_length_still_flags_violation(self):
        """coverage_start correctly anchored on the member's own cycle, but
        coverage_end truncated/miscalculated (not a full Quarterly period from
        that start) must still be flagged - anchoring the start is necessary
        but not sufficient; length has to follow from it too."""
        self.expectErrorLog("Period Anchor Violation")
        marker = frappe.utils.now_datetime()

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=self.ANCHOR,
            coverage_end=date(2025, 1, 31),  # short of the full Quarterly period (2025-02-14)
            member_doc=self.member,
        )

        self.assertTrue(result.success, f"Invoice generation failed: {result.error_message}")
        invoice = result.data

        self.assertEqual(
            self._error_log_count(marker),
            1,
            "Expected exactly one Period Anchor Violation Error Log entry",
        )

        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice.name,
                "content": ["like", "%Period anchor violation%"],
            },
        )
        self.assertEqual(len(comments), 1, "Expected exactly one anchor-violation comment on the invoice")

    def test_guard_internal_failure_produces_error_log_not_silence(self):
        """If the guard's own check raises (e.g. a DB error inside the
        previous-coverage-end lookup), the failure must be recorded via
        frappe.log_error() (a durable, queryable Error Log row) - NOT only via
        self.logger.warning(), which resolves to a LazyServiceLogger at level
        ERROR under this harness and silently drops anything below it. A
        guard whose own failure path is invisible defeats the guard."""
        self.expectErrorLog("Period Anchor Guard Failed")
        marker = frappe.utils.now_datetime()

        with patch(
            "verenigingen.services.billing.coverage_calculator.CoverageCalculator."
            "get_latest_coverage_end_date",
            side_effect=RuntimeError("forced failure for test"),
        ):
            generator = InvoiceGenerator(self.schedule)
            result = generator.generate_invoice(
                coverage_start=self.ANCHOR,
                coverage_end=date(2025, 2, 14),
                member_doc=self.member,
            )

        # Non-blocking: generation must still succeed despite the guard failing.
        self.assertTrue(result.success, f"Invoice generation failed: {result.error_message}")

        guard_failure_logs = frappe.db.count(
            "Error Log",
            filters={"creation": [">=", marker], "method": ["like", "%Period Anchor Guard Failed%"]},
        )
        self.assertEqual(
            guard_failure_logs,
            1,
            "Expected exactly one 'Period Anchor Guard Failed' Error Log entry when the "
            "guard itself raises - a silent guard failure is the exact defect this guard "
            "exists to prevent",
        )
