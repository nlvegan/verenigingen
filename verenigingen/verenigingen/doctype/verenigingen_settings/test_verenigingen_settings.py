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

    def test_sales_invoice_account_handler_uses_dues_receivable_for_membership(self):
        """A membership Sales Invoice whose debit_to is the company default must be
        switched to the VPS dues_payments_receivable_account by the account handler.

        Exercises set_membership_receivable_account() end-to-end against real Accounts
        + a real Verenigingen Payments Settings value (previously an unconditional
        skipTest -- the account-parent setup is handled via a sibling of the company
        default, no hardcoded chart-of-accounts names)."""
        from verenigingen.services.billing.sales_invoice_account_handler import (
            set_membership_receivable_account,
        )

        company = self._get_test_company()
        company_default = self._get_or_create_receivable_account(company)
        dues_account = self._make_dues_receivable_account(company, company_default)

        vps = frappe.get_single("Verenigingen Payments Settings")
        vps.dues_payments_receivable_account = dues_account
        vps.save()

        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = company
        invoice.debit_to = company_default  # starts at the company default
        invoice.append(
            "items",
            {
                "item_name": "Membership Dues",
                "item_group": "Membership",
                "qty": 1,
                "rate": 25.0,
            },
        )

        set_membership_receivable_account(invoice)

        self.assertEqual(
            invoice.debit_to,
            dues_account,
            "membership invoice at the company default must switch to the VPS dues account",
        )

    def test_non_membership_invoice_keeps_company_default(self):
        """A non-membership invoice (no membership item, non-member customer) must keep
        its company-default debit_to -- the handler only overrides membership invoices."""
        from verenigingen.services.billing.sales_invoice_account_handler import (
            set_membership_receivable_account,
        )

        company = self._get_test_company()
        company_default = self._get_or_create_receivable_account(company)
        dues_account = self._make_dues_receivable_account(company, company_default)

        vps = frappe.get_single("Verenigingen Payments Settings")
        vps.dues_payments_receivable_account = dues_account
        vps.save()

        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = company
        invoice.debit_to = company_default
        invoice.append(
            "items",
            {
                "item_name": "General Service",
                "item_group": "Services",
                "qty": 1,
                "rate": 100.0,
            },
        )

        set_membership_receivable_account(invoice)

        self.assertEqual(
            invoice.debit_to,
            company_default,
            "non-membership invoice must keep the company default debit_to",
        )

    def _make_dues_receivable_account(self, company, company_default):
        """Create a distinct non-group Receivable account as a sibling of the company
        default, to stand in for VPS.dues_payments_receivable_account. Tracked for
        cleanup; no commit, so the test transaction rolls it back."""
        parent = frappe.db.get_value("Account", company_default, "parent_account")
        account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": f"Test Dues Receivable {frappe.generate_hash(length=6)}",
                "account_type": "Receivable",
                "parent_account": parent,
                "company": company,
            }
        )
        account.insert()
        self.track_doc("Account", account.name)
        return account.name

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
