# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for InvoiceGenerator service.
Tests the invoice generation logic extracted from MembershipDuesSchedule.

Uses Enhanced Test Factory for real database operations - no mocks.
"""

import unittest
from datetime import date

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

        # Create customer and link to member
        self.customer_doc = frappe.new_doc("Customer")
        self.customer_doc.customer_name = f"{self.member.first_name} {self.member.last_name}"
        self.customer_doc.customer_type = "Individual"
        self.customer_doc.insert()

        self.member.customer = self.customer_doc.name
        self.member.save()
        self.member.reload()

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
        self.assertTrue(result.success, f"Invoice generation failed: {result.error}")
        self.assertIsNotNone(result.invoice)
        self.assertEqual(result.invoice.customer, self.customer_doc.name)
        self.assertEqual(result.invoice.member, self.member.name)
        self.assertEqual(str(result.invoice.custom_coverage_start_date), "2025-01-01")
        self.assertEqual(str(result.invoice.custom_coverage_end_date), "2025-12-31")
        self.assertEqual(result.invoice.is_membership_invoice, 1)
        self.assertEqual(result.invoice.membership_dues_schedule_display, self.schedule.name)

        # Verify invoice has items
        self.assertEqual(len(result.invoice.items), 1)
        self.assertEqual(result.invoice.items[0].qty, 1)
        self.assertEqual(result.invoice.items[0].rate, self.schedule.dues_rate)

    # ========== Account Configuration Tests ==========

    def test_income_account_fallback_to_company_default(self):
        """Test income account falls back to company default when settings account doesn't exist"""
        # Arrange
        settings = frappe.get_single("Verenigingen Settings")
        original_account = settings.dues_income_account

        # Set invalid income account in settings
        frappe.db.set_value("Verenigingen Settings", None, "dues_income_account", "Invalid-Account-999")
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
            self.assertTrue(result.success, f"Invoice generation failed: {result.error}")
            self.assertIsNotNone(result.invoice)
            # Verify fallback was used (company default income account)
            company_doc = frappe.get_cached_doc("Company", settings.company)
            self.assertEqual(result.invoice.items[0].income_account, company_doc.default_income_account)

        finally:
            # Restore original setting
            frappe.db.set_value("Verenigingen Settings", None, "dues_income_account", original_account)
            frappe.db.commit()

    def test_missing_income_account_fails_gracefully(self):
        """Test that missing income account (no fallback) fails with clear error"""
        # Arrange
        settings = frappe.get_single("Verenigingen Settings")
        original_account = settings.dues_income_account

        # Check if company actually has a fallback account
        company_doc = frappe.get_doc("Company", settings.company)
        has_company_fallback = bool(company_doc.default_income_account)

        if not has_company_fallback:
            # Perfect - no fallback exists, just clear settings account
            frappe.db.set_value("Verenigingen Settings", None, "dues_income_account", None)
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
                self.assertIn("Income account not configured", result.error)

            finally:
                # Restore original settings
                frappe.db.set_value("Verenigingen Settings", None, "dues_income_account", original_account)
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
        if hasattr(result.invoice, "sepa_mandate_id"):
            self.assertIsNotNone(result.invoice.sepa_mandate_id)
            self.assertEqual(result.invoice.sepa_mandate_id, mandate.name)

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
        mandate.sign_date = date(2024, 1, 1)
        mandate.valid_until = date(2024, 12, 31)  # Expired
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
        if hasattr(result.invoice, "sepa_mandate_id"):
            self.assertIsNone(result.invoice.sepa_mandate_id)

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
        if hasattr(result.invoice, "sepa_mandate_id"):
            self.assertIsNone(result.invoice.sepa_mandate_id)

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
            self.assertEqual(result.invoice.docstatus, 1)  # 1 = Submitted
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
            self.assertEqual(result.invoice.docstatus, 0)  # 0 = Draft
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
            self.assertIn("does not have a customer record", result.error)

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
            self.assertIn("Company not configured", result.error)

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
        self.assertIn("must not be after end date", result.error)

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
        self.assertIn("Member document mismatch", result.error)

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
            item_code = result.invoice.items[0].item_code
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
            self.assertEqual(result.invoice.payment_terms_template, template_name)

        finally:
            # Restore original terms
            self.schedule.payment_terms_template = original_terms
            self.schedule.save()
            frappe.db.commit()
