# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVerenigingenSettings(EnhancedTestCase):
    """Test Verenigingen Settings functionality"""

    def test_dues_payments_receivable_account_field_migrated(self):
        """dues_payments_receivable_account is a Link->Account on Payments Settings.

        The field was migrated out of Verenigingen Settings into Verenigingen
        Payments Settings. This is a schema drift guard: it asserts the field is
        present with the correct type/options on the migration target, so a
        removal or type change is caught. (Previously an unconditional skipTest.)
        """
        field = frappe.get_meta("Verenigingen Payments Settings").get_field(
            "dues_payments_receivable_account"
        )
        self.assertIsNotNone(field, "dues_payments_receivable_account missing from Payments Settings")
        self.assertEqual(field.fieldtype, "Link")
        self.assertEqual(field.options, "Account")

    def test_dues_income_account_field_migrated(self):
        """dues_income_account is a Link->Account on Verenigingen Payments Settings.

        Schema drift guard for the field migrated out of Verenigingen Settings.
        (Previously an unconditional skipTest.)
        """
        field = frappe.get_meta("Verenigingen Payments Settings").get_field("dues_income_account")
        self.assertIsNotNone(field, "dues_income_account missing from Payments Settings")
        self.assertEqual(field.fieldtype, "Link")
        self.assertEqual(field.options, "Account")

    def test_sales_invoice_account_handler_integration(self):
        """Test that the account handler correctly uses the dues_payments_receivable_account field"""
        # TODO: This test requires complex ERPNext Account setup with parent accounts
        # Skipping for now - needs investigation of Account creation dependencies
        self.skipTest("Complex ERPNext Account setup with parent account dependencies - needs investigation")

        from verenigingen.services.billing.sales_invoice_account_handler import (
            set_membership_receivable_account,
        )

        # Create test accounts
        company_default_account = self.create_test_account(
            account_name="Company Default Receivable", account_type="Receivable"
        )

        dues_receivable_account = self.create_test_account(
            account_name="Dues Specific Receivable", account_type="Receivable"
        )

        # Configure Verenigingen Payments Settings (dues accounts are now there)
        payments_settings = frappe.get_single("Verenigingen Payments Settings")
        payments_settings.dues_payments_receivable_account = dues_receivable_account
        payments_settings.save()

        # Get company from main settings
        settings = frappe.get_single("Verenigingen Settings")

        # Configure Company with default receivable account
        company = frappe.get_doc("Company", settings.company)
        company.default_receivable_account = company_default_account
        company.save()

        # Create a test member and customer
        member = self.create_test_member(first_name="Test", last_name="Member")

        # Create mock Sales Invoice with membership item
        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = settings.company
        invoice.customer = member.customer
        invoice.debit_to = company_default_account  # Start with company default

        # Add membership item
        invoice.append(
            "items",
            {
                "item_code": "MEMBERSHIP-ITEM",
                "item_name": "Membership Dues",
                "item_group": "Membership",
                "qty": 1,
                "rate": 25.0,
            },
        )

        # Test the account handler function
        set_membership_receivable_account(invoice)

        # Verify account was changed to dues-specific account
        self.assertEqual(
            invoice.debit_to,
            dues_receivable_account,
            "Invoice should use dues_payments_receivable_account for membership invoices",
        )

    def test_non_membership_invoice_unchanged(self):
        """Test that non-membership invoices keep the company default account"""
        # TODO: This test requires complex ERPNext Account setup with parent accounts
        # Skipping for now - needs investigation of Account creation dependencies
        self.skipTest("Complex ERPNext Account setup with parent account dependencies - needs investigation")

        from verenigingen.services.billing.sales_invoice_account_handler import (
            set_membership_receivable_account,
        )

        # Create test accounts
        company_default_account = self.create_test_account(
            account_name="Company Default Receivable 2", account_type="Receivable"
        )

        dues_receivable_account = self.create_test_account(
            account_name="Dues Specific Receivable 2", account_type="Receivable"
        )

        # Configure Verenigingen Payments Settings (dues accounts are now there)
        payments_settings = frappe.get_single("Verenigingen Payments Settings")
        payments_settings.dues_payments_receivable_account = dues_receivable_account
        payments_settings.save()

        # Get company from main settings
        settings = frappe.get_single("Verenigingen Settings")

        company = frappe.get_doc("Company", settings.company)
        company.default_receivable_account = company_default_account
        company.save()

        # Create mock Sales Invoice with non-membership item
        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = settings.company
        invoice.customer = "Customer-001"  # Non-member customer
        invoice.debit_to = company_default_account

        # Add non-membership item
        invoice.append(
            "items",
            {
                "item_code": "SERVICE-ITEM",
                "item_name": "General Service",
                "item_group": "Services",
                "qty": 1,
                "rate": 100.0,
            },
        )

        # Test the account handler
        original_debit_to = invoice.debit_to
        set_membership_receivable_account(invoice)

        # Verify account was NOT changed
        self.assertEqual(
            invoice.debit_to,
            original_debit_to,
            "Non-membership invoices should keep original debit_to account",
        )

    def test_account_handler_error_handling(self):
        """Test that the account handler handles errors gracefully"""
        from verenigingen.services.billing.sales_invoice_account_handler import (
            set_membership_receivable_account,
        )

        # Test with invoice that has no debit_to
        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = "Test Company"
        invoice.customer = "Test Customer"
        invoice.debit_to = None

        # Should not raise an exception
        try:
            set_membership_receivable_account(invoice)
            self.assertIsNone(invoice.debit_to, "Invoice with no debit_to should remain None")
        except Exception as e:
            self.fail(f"Account handler should not raise exception for invoice without debit_to: {e}")

    def test_validate_donation_configuration_no_attribute_error(self):
        """validate_donation_configuration() must not crash on the removed default_donation_type field.

        default_donation_type was removed from the Verenigingen Settings doctype
        (the data model now uses Donation.donation_purpose_type). The validation
        endpoint read it via direct attribute access, raising AttributeError on
        every call. It must now read it defensively and report None.
        """
        from verenigingen.verenigingen.doctype.verenigingen_settings.verenigingen_settings import (
            validate_donation_configuration,
        )

        self._as_admin()
        result = validate_donation_configuration()

        self.assertIn("configuration", result)
        # The removed field is reported defensively as None rather than crashing.
        self.assertIsNone(result["configuration"]["default_donation_type"])

    def _as_admin(self):
        """Switch the session to Administrator to exercise the admin-only endpoint."""
        frappe.set_user("Administrator")

    def create_test_account(self, account_name, account_type="Receivable", parent_account=None):
        """Helper method to create test accounts"""
        if frappe.db.exists("Account", account_name):
            return account_name

        settings = frappe.get_single("Verenigingen Settings")
        company = settings.company

        # Get parent account if not specified
        if not parent_account:
            if account_type == "Receivable":
                parent_account = frappe.db.get_value(
                    "Account", {"account_type": "Receivable", "is_group": 1, "company": company}, "name"
                )
            if not parent_account:
                # Fallback to a known group account
                parent_account = "Accounts Receivable - TC"

        account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": account_name,
                "account_type": account_type,
                "parent_account": parent_account,
                "company": company,
            }
        )
        account.insert()
        frappe.db.commit()

        return account.name
