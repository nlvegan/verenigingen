# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Branch / edge-case coverage for InvoiceGenerator service.

The happy path and the due-date regression are already covered by
``test_invoice_generator.py`` and ``test_regression_invoice_due_date_calculation.py``.
This module targets the ERROR and FALLBACK branches that those suites leave
uncovered:

    - _validate_inputs rejection branches (missing dates, period too long,
      too far past/future, negative dues rate).
    - _get_income_account / _get_expense_account / _get_cost_center fallbacks.
    - _validate_sepa_mandate rejection branches (member mismatch, no sign date,
      future sign date, expired, no IBAN, malformed IBAN).
    - _create_membership_dues_item idempotency.

Real database operations via EnhancedTestCase — no mocks of ERPNext/Frappe.
"""

from datetime import date, timedelta

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.billing.invoice_generator import (
    InvoiceDescriptionBuilder,
    InvoiceGenerator,
    MembershipDuesItemManager,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestInvoiceGeneratorBranches(EnhancedTestCase):
    """Exercise the error / fallback branches of InvoiceGenerator."""

    def setUp(self):
        super().setUp()

        self.member = self.create_test_member(first_name="Branch", last_name="Test", birth_date="1985-05-15")
        self.customer_doc = self.link_member_to_customer(self.member)
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name="Regular Member"
        )
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1,
        )
        if not schedules:
            frappe.throw("No schedule was created with membership")
        self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        self.member.reload()
        self.generator = InvoiceGenerator(self.schedule)

    # ====================================================================
    # _validate_inputs rejection branches
    # ====================================================================

    def test_missing_coverage_dates_rejected(self):
        """Both coverage dates required — passing None must fail with a clear message."""
        result = self.generator.generate_invoice(
            coverage_start=None, coverage_end=date(2025, 12, 31), member_doc=self.member
        )
        self.assertFalse(result.success)
        self.assertIn("required", result.error_message)
        self.assertIsNone(result.data)

    def test_missing_coverage_end_rejected(self):
        """coverage_end=None hits the same required-dates guard."""
        result = self.generator.generate_invoice(
            coverage_start=date(2025, 1, 1), coverage_end=None, member_doc=self.member
        )
        self.assertFalse(result.success)
        self.assertIn("required", result.error_message)

    def test_coverage_period_exceeding_max_rejected(self):
        """A coverage span beyond MAX_COVERAGE_PERIOD_YEARS must be rejected.

        Anchored on today() so it also stays within the past/future windows that
        are checked AFTER the duration check (so duration is what trips first)."""
        start = getdate(today())
        end = add_days(start, 365 * (InvoiceGenerator.MAX_COVERAGE_PERIOD_YEARS + 1))
        result = self.generator.generate_invoice(
            coverage_start=start, coverage_end=end, member_doc=self.member
        )
        self.assertFalse(result.success)
        self.assertIn("exceeds maximum allowed duration", result.error_message)

    def test_coverage_start_too_far_in_past_rejected(self):
        """A coverage_start more than MAX_PAST_DATE_YEARS in the past is rejected."""
        # Short 1-day window (so the duration check passes) but anchored far in the past.
        start = date.today() - timedelta(days=365 * (InvoiceGenerator.MAX_PAST_DATE_YEARS + 1))
        end = start + timedelta(days=1)
        result = self.generator.generate_invoice(
            coverage_start=start, coverage_end=end, member_doc=self.member
        )
        self.assertFalse(result.success)
        self.assertIn("in the past", result.error_message)

    def test_coverage_start_too_far_in_future_rejected(self):
        """A coverage_start more than MAX_FUTURE_DATE_YEARS in the future is rejected."""
        start = date.today() + timedelta(days=365 * (InvoiceGenerator.MAX_FUTURE_DATE_YEARS + 1))
        end = start + timedelta(days=1)
        result = self.generator.generate_invoice(
            coverage_start=start, coverage_end=end, member_doc=self.member
        )
        self.assertFalse(result.success)
        self.assertIn("in the future", result.error_message)

    def test_negative_dues_rate_rejected(self):
        """A negative dues_rate on the schedule is invalid (0 is allowed, <0 is not)."""
        # dues_rate is read into the generator at construction time.
        self.generator.dues_rate = -5.0
        result = self.generator.generate_invoice(
            coverage_start=date(2025, 1, 1), coverage_end=date(2025, 12, 31), member_doc=self.member
        )
        self.assertFalse(result.success)
        self.assertIn("Invalid dues rate", result.error_message)

    def test_zero_dues_rate_allowed(self):
        """dues_rate == 0 (free membership) must pass validation and produce an invoice."""
        self.generator.dues_rate = 0.0
        result = self.generator.generate_invoice(
            coverage_start=date(2025, 1, 1), coverage_end=date(2025, 12, 31), member_doc=self.member
        )
        self.assertTrue(result.success, f"Zero-rate invoice failed: {result.error_message}")
        self.assertEqual(result.data.items[0].rate, 0.0)

    def test_member_doc_mismatch_rejected(self):
        """A member_doc whose name differs from the schedule's member is rejected
        (guards against billing the wrong member). Distinct from the AttributeError
        path: this hits the explicit 'Member document mismatch' branch with valid dates."""
        other = self.create_test_member(first_name="Wrong", last_name="Member", birth_date="1990-01-01")
        result = self.generator.generate_invoice(
            coverage_start=date(2025, 1, 1), coverage_end=date(2025, 12, 31), member_doc=other
        )
        self.assertFalse(result.success)
        self.assertIn("Member document mismatch", result.error_message)
        self.assertIsNone(result.data)

    def test_unexpected_exception_returned_not_raised(self):
        """generate_invoice never raises — an unexpected error deep in the pipeline
        (here: a member_doc missing the .name attribute) is caught by the outer
        handler and returned as a failed OperationResult."""

        class BrokenMember:
            # No .name attribute -> AttributeError inside _validate_inputs,
            # which is not one of the validation-string returns.
            customer = self.customer_doc.name

        # handle_error(...raise_error=False) deliberately writes an Error Log for the
        # swallowed exception — that is the documented behaviour of this branch, not a bug.
        self.expectErrorLog("InvoiceGenerator")
        result = self.generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 12, 31),
            member_doc=BrokenMember(),
        )
        self.assertFalse(result.success)
        self.assertIn("Invoice generation failed", result.error_message)
        self.assertIsNone(result.data)

    # ====================================================================
    # Account / cost-center resolution helpers (direct, real DB)
    # ====================================================================

    def test_income_account_company_default_invalid_returns_none(self):
        """When BOTH the payments-settings account and the company default income
        account point at nonexistent Accounts, _get_income_account returns None
        (the two warning branches), and the full pipeline then fails clearly."""
        settings = frappe.get_single("Verenigingen Settings")
        company = settings.company
        orig_settings_acct = frappe.db.get_value(
            "Verenigingen Payments Settings", None, "dues_income_account"
        )
        orig_company_acct = frappe.db.get_value("Company", company, "default_income_account")

        frappe.db.set_value(
            "Verenigingen Payments Settings", None, "dues_income_account", "Bad-Settings-Income-999"
        )
        frappe.db.set_value("Company", company, "default_income_account", "Bad-Company-Income-999")
        frappe.db.commit()
        frappe.clear_cache(doctype="Company")
        try:
            self.assertIsNone(self.generator._get_income_account(settings, company))

            # And the early-return in generate_invoice surfaces a clear error.
            result = self.generator.generate_invoice(
                coverage_start=date(2025, 1, 1),
                coverage_end=date(2025, 12, 31),
                member_doc=self.member,
            )
            self.assertFalse(result.success)
            self.assertIn("Income account not configured", result.error_message)
        finally:
            frappe.db.set_value(
                "Verenigingen Payments Settings", None, "dues_income_account", orig_settings_acct
            )
            frappe.db.set_value("Company", company, "default_income_account", orig_company_acct)
            frappe.db.commit()
            frappe.clear_cache(doctype="Company")

    def test_expense_account_invalid_returns_none(self):
        """When the company default_expense_account points at a nonexistent Account,
        _get_expense_account returns None (the warning branch)."""
        settings = frappe.get_single("Verenigingen Settings")
        company = settings.company
        original = frappe.db.get_value("Company", company, "default_expense_account")
        frappe.db.set_value("Company", company, "default_expense_account", "Nonexistent-Expense-999")
        frappe.db.commit()
        try:
            # Clear the cached company doc so the helper reads the mutated value.
            frappe.clear_cache(doctype="Company")
            result = self.generator._get_expense_account(company)
            self.assertIsNone(result)
        finally:
            frappe.db.set_value("Company", company, "default_expense_account", original)
            frappe.db.commit()
            frappe.clear_cache(doctype="Company")

    def test_expense_account_company_does_not_exist_returns_none(self):
        """A nonexistent company name resolves to None (DoesNotExistError branch)."""
        result = self.generator._get_expense_account("Nonexistent Company XYZ-123")
        self.assertIsNone(result)

    def test_income_account_company_does_not_exist_returns_none(self):
        """Income-account fallback also tolerates a nonexistent company."""
        settings = frappe.get_single("Verenigingen Settings")
        # Force the payments-settings primary to be invalid so we reach the company fallback,
        # and pass a bogus company so the company branch raises DoesNotExistError.
        original = frappe.db.get_value("Verenigingen Payments Settings", None, "dues_income_account")
        frappe.db.set_value("Verenigingen Payments Settings", None, "dues_income_account", "Bad-Income-999")
        frappe.db.commit()
        try:
            result = self.generator._get_income_account(settings, "Nonexistent Company XYZ-123")
            self.assertIsNone(result)
        finally:
            frappe.db.set_value("Verenigingen Payments Settings", None, "dues_income_account", original)
            frappe.db.commit()

    def test_cost_center_falls_back_to_main_when_no_company_default(self):
        """With no chapter and no Company.cost_center set, _get_cost_center finds the
        'Main' cost center for the company (priority steps 3/4)."""
        settings = frappe.get_single("Verenigingen Settings")
        company = settings.company
        original_cc = frappe.db.get_value("Company", company, "cost_center")
        # Clear the company default so resolution must fall through to the Main lookup.
        frappe.db.set_value("Company", company, "cost_center", None)
        frappe.db.commit()
        try:
            # member with no chapter -> chapter lookup returns None -> Main fallback
            cost_center = self.generator._get_cost_center(company, self.member)
            self.assertIsNotNone(cost_center, "Expected a Main cost center fallback")
            # The returned cost center must actually belong to this company.
            self.assertEqual(frappe.db.get_value("Cost Center", cost_center, "company"), company)
        finally:
            frappe.db.set_value("Company", company, "cost_center", original_cc)
            frappe.db.commit()

    def test_cost_center_unknown_company_returns_none(self):
        """A company with no cost centers at all yields None (final warning branch)."""
        result = self.generator._get_cost_center("Nonexistent Company XYZ-123", member_doc=None)
        self.assertIsNone(result)

    # ====================================================================
    # _validate_sepa_mandate rejection branches
    # ====================================================================

    def _make_valid_mandate(self, member=None, sign_date=None):
        """Create a valid, insertable SEPA mandate for this member."""
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.member = member or self.member.name
        mandate.customer = self.customer_doc.name
        mandate.status = "Active"
        mandate.is_active = 1
        mandate.used_for_memberships = 1
        mandate.iban = "NL91ABNA0417164300"
        mandate.account_holder_name = f"{self.member.first_name} {self.member.last_name}"
        mandate.sign_date = sign_date or date(2024, 1, 1)
        mandate.insert()
        frappe.db.commit()
        return mandate

    def test_validate_sepa_mandate_member_mismatch(self):
        """A mandate whose member differs from the invoice member is rejected."""
        other = self.create_test_member(first_name="Mismatch", last_name="Holder", birth_date="1990-02-02")
        mandate = self._make_valid_mandate(member=other.name)
        error = self.generator._validate_sepa_mandate(mandate.name, self.member)
        self.assertIsNotNone(error)
        self.assertIn("does not match", error)

    def test_validate_sepa_mandate_no_sign_date(self):
        """A mandate with no sign_date is rejected (set via db to bypass reqd-on-insert)."""
        mandate = self._make_valid_mandate()
        frappe.db.set_value("SEPA Mandate", mandate.name, "sign_date", None)
        frappe.db.commit()
        error = self.generator._validate_sepa_mandate(mandate.name, self.member)
        self.assertEqual(error, "Mandate has no sign date")

    def test_validate_sepa_mandate_future_sign_date(self):
        """A sign_date in the future is rejected."""
        mandate = self._make_valid_mandate()
        future = date.today() + timedelta(days=30)
        frappe.db.set_value("SEPA Mandate", mandate.name, "sign_date", future)
        frappe.db.commit()
        error = self.generator._validate_sepa_mandate(mandate.name, self.member)
        self.assertIsNotNone(error)
        self.assertIn("in the future", error)

    def test_validate_sepa_mandate_expired(self):
        """An expiry_date in the past is rejected."""
        mandate = self._make_valid_mandate()
        past = date.today() - timedelta(days=1)
        frappe.db.set_value("SEPA Mandate", mandate.name, "expiry_date", past)
        frappe.db.commit()
        error = self.generator._validate_sepa_mandate(mandate.name, self.member)
        self.assertIsNotNone(error)
        self.assertIn("expired", error)

    def test_validate_sepa_mandate_no_iban(self):
        """A mandate with no IBAN is rejected."""
        mandate = self._make_valid_mandate()
        frappe.db.set_value("SEPA Mandate", mandate.name, "iban", None)
        frappe.db.commit()
        error = self.generator._validate_sepa_mandate(mandate.name, self.member)
        self.assertEqual(error, "Mandate has no IBAN")

    def test_validate_sepa_mandate_malformed_iban(self):
        """A mandate carrying a malformed IBAN is rejected by the IBAN validator."""
        mandate = self._make_valid_mandate()
        frappe.db.set_value("SEPA Mandate", mandate.name, "iban", "GARBAGE123")
        frappe.db.commit()
        error = self.generator._validate_sepa_mandate(mandate.name, self.member)
        self.assertIsNotNone(error)
        self.assertIn("Invalid IBAN", error)

    def test_validate_sepa_mandate_valid_returns_none(self):
        """A fully valid mandate passes validation (None)."""
        mandate = self._make_valid_mandate()
        error = self.generator._validate_sepa_mandate(mandate.name, self.member)
        self.assertIsNone(error)

    def test_validate_sepa_mandate_nonexistent_returns_error(self):
        """Looking up a nonexistent mandate is caught and returned as an error string,
        never raised (the broad except in _validate_sepa_mandate)."""
        error = self.generator._validate_sepa_mandate("SEPA-DOES-NOT-EXIST-999", self.member)
        self.assertIsNotNone(error)
        self.assertIn("Failed to validate mandate", error)

    def test_valid_mandate_selects_sepa_direct_debit_in_payment_config(self):
        """A fully valid Active mandate matching the selection filter makes
        _get_payment_configuration choose SEPA Direct Debit and carry the mandate id
        (the success branch at invoice_generator.py:566-569)."""
        mandate = self._make_valid_mandate()
        config = self.generator._get_payment_configuration(self.member)
        self.assertEqual(config["payment_method"], "SEPA Direct Debit")
        self.assertEqual(config["sepa_mandate_id"], mandate.name)

    def test_invalid_mandate_falls_back_to_bank_transfer_in_payment_config(self):
        """End-to-end: an Active mandate that fails deep validation makes
        _get_payment_configuration fall back to Bank Transfer (no SEPA id)."""
        mandate = self._make_valid_mandate()
        # Corrupt the IBAN so deep validation fails, while it still matches the
        # Active/is_active/used_for_memberships filter that selects it.
        frappe.db.set_value("SEPA Mandate", mandate.name, "iban", "GARBAGE123")
        frappe.db.commit()

        config = self.generator._get_payment_configuration(self.member)
        self.assertEqual(config["payment_method"], "Bank Transfer")
        self.assertIsNone(config["sepa_mandate_id"])

    # ====================================================================
    # Item manager / description builder
    # ====================================================================

    def test_create_membership_dues_item_idempotent(self):
        """Ensuring the item exists twice must not raise and returns a stable code."""
        income = frappe.db.get_value(
            "Company",
            frappe.get_single("Verenigingen Settings").company,
            "default_income_account",
        )
        code1 = self.generator._create_membership_dues_item(income, None)
        code2 = self.generator._create_membership_dues_item(income, None)
        self.assertEqual(code1, code2)
        self.assertTrue(frappe.db.exists("Item", code1))

    def test_item_name_custom_frequency(self):
        """Custom-frequency item name embeds the configured number/unit."""
        mgr = MembershipDuesItemManager()
        name = mgr.get_item_name("Custom", {"number": 2, "unit": "Weeks"})
        self.assertEqual(name, "Membership Dues - Custom (Every 2 Weeks)")

    def test_item_name_custom_without_settings_uses_plain_name(self):
        """Custom frequency with no/empty settings dict is falsy, so it takes the
        else-branch and produces the plain 'Membership Dues - Custom' name (no
        '(Every N ...)' suffix)."""
        mgr = MembershipDuesItemManager()
        self.assertEqual(mgr.get_item_name("Custom", {}), "Membership Dues - Custom")
        self.assertEqual(mgr.get_item_name("Custom", None), "Membership Dues - Custom")

    def test_item_name_custom_frequency_defaults_within_settings(self):
        """A truthy custom_settings missing 'number'/'unit' keys defaults to 1 Months."""
        mgr = MembershipDuesItemManager()
        name = mgr.get_item_name("Custom", {"other": "x"})
        self.assertEqual(name, "Membership Dues - Custom (Every 1 Months)")

    def test_description_builder_daily(self):
        """Daily frequency produces the single-day description form."""
        desc = InvoiceDescriptionBuilder().build_description(
            member_name="Jane Doe",
            membership_type="Regular",
            billing_frequency="Daily",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 1),
        )
        self.assertIn("Daily fee for 2025-01-01", desc)

    def test_description_builder_fallback_frequency(self):
        """An unrecognised frequency uses the generic period form."""
        desc = InvoiceDescriptionBuilder().build_description(
            member_name="Jane Doe",
            membership_type="Regular",
            billing_frequency="Weekly",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 7),
        )
        self.assertIn("Period: 2025-01-01 to 2025-01-07", desc)
