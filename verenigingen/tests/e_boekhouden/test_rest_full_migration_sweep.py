"""
Coverage sweep for genuinely-uncovered paths in
verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py

Scope chosen AFTER auditing the existing suite to avoid duplication. The
following are already exercised elsewhere and are NOT retested here:
  - should_skip_mutation, ensure_account_type_is_correct, _resolve_account_mapping,
    analyze_import_failures, migration_status_summary, get_mutation_gap_report,
    create_invoice_line_for_tegenrekening
        -> test_rest_migration_helpers.py
  - _get_or_create_customer / _supplier / _company_party / company_as_*
        -> test_rest_party_dispatch.py
  - _check_if_already_imported / _check_if_invoice_number_exists /
    _get_memorial_booking_amounts / _get_bank_transaction_stats /
    _retry_transient_failures / _finalize_mutation_savepoint /
    _validate_memorial_booking
        -> test_rest_full_migration_helpers_coverage.py

This file targets the residual, deterministic, DB-testable logic:
  - _get_or_create_temporary_diff_account : the PRIORITY 1 / PRIORITY 2 lookup
    branches that the full suite never hits (the canonical test company only
    owns an *Asset* Temporary account, so only PRIORITY 3 is otherwise covered).
  - debug_single_mutation : pins a confirmed production bug (reads a settings
    field that does not exist) so it stays visible until fixed.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_full_migration_sweep
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _get_or_create_temporary_diff_account,
    debug_single_mutation,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


# ---------------------------------------------------------------------------
# _get_or_create_temporary_diff_account: priority-based existing-account lookup
# ---------------------------------------------------------------------------
class TestTemporaryDiffAccountResolution(EnhancedTestCase):
    """Resolve the balancing account for opening balances by priority.

    PRIORITY 1: an Equity 'Temporary' account whose name mentions 'Difference'.
    PRIORITY 2: any Equity 'Temporary' account.
    PRIORITY 3: any 'Temporary' account regardless of root type (fallback).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.equity_group = frappe.db.get_value(
            "Account", {"company": cls.company, "root_type": "Equity", "is_group": 1}, "name"
        )

    def _make_equity_temp_account(self, account_name):
        """Persist an Equity / Temporary leaf account for the test company."""
        acct = frappe.new_doc("Account")
        acct.account_name = account_name
        acct.parent_account = self.equity_group
        acct.company = self.company
        acct.account_type = "Temporary"
        acct.root_type = "Equity"
        acct.is_group = 0
        acct.insert(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc("Account", acct.name, force=True))
        return acct.name

    def test_priority1_temporary_differences_equity_account_returned(self):
        """An Equity 'Temporary Differences' account wins PRIORITY 1 selection."""
        name = self._make_equity_temp_account("Temporary Differences")
        debug = []
        result = _get_or_create_temporary_diff_account(self.company, debug)
        self.assertEqual(result, name)
        self.assertTrue(any("Using existing temporary account:" in m for m in debug))
        # It must NOT fall through to the equity/any fallback messages.
        self.assertFalse(any("equity temporary account" in m for m in debug))

    def test_priority2_equity_temp_without_difference_name_returned(self):
        """An Equity Temporary account NOT mentioning 'Difference' is found at
        PRIORITY 2 (PRIORITY 1's name filter does not match it)."""
        name = self._make_equity_temp_account("Suspense Equity Temp")
        debug = []
        result = _get_or_create_temporary_diff_account(self.company, debug)
        self.assertEqual(result, name)
        self.assertTrue(any("Using existing equity temporary account:" in m for m in debug))

    def test_priority1_preferred_over_priority2(self):
        """When both a 'Difference' Equity-temp and a plain Equity-temp exist,
        the 'Difference' one (PRIORITY 1) is selected."""
        diff_name = self._make_equity_temp_account("Temporary Differences")
        plain_name = self._make_equity_temp_account("Suspense Equity Temp")
        debug = []
        result = _get_or_create_temporary_diff_account(self.company, debug)
        self.assertEqual(result, diff_name)
        self.assertNotEqual(result, plain_name)

    def test_priority3_fallback_to_non_equity_temporary_account(self):
        """With no Equity Temporary account, any 'Temporary' account (e.g. the
        canonical Asset 'Temporary Opening') is used at PRIORITY 3."""
        debug = []
        result = _get_or_create_temporary_diff_account(self.company, debug)
        self.assertIsNotNone(result)
        # The resolved account really is a Temporary account for this company.
        self.assertEqual(
            frappe.db.get_value("Account", result, "account_type"), "Temporary"
        )
        self.assertEqual(frappe.db.get_value("Account", result, "company"), self.company)
        # PRIORITY 3 fallback emits the root-annotated message.
        self.assertTrue(any("Using existing temporary account (root:" in m for m in debug))


# ---------------------------------------------------------------------------
# debug_single_mutation: confirmed production bug
# ---------------------------------------------------------------------------
class TestDebugSingleMutationCompanyField(EnhancedTestCase):
    """Regression guard for a fixed bug.

    debug_single_mutation used to read ``settings.company``, but the
    E-Boekhouden Settings DocType has no ``company`` field -- the field is
    ``default_company`` (used correctly everywhere else in this module, e.g.
    line 196 / 2905 / 3468). The resulting AttributeError was swallowed by the
    outer ``except``, so debug_single_mutation ALWAYS returned
    ``{"success": False, "error": "...has no attribute 'company'"}`` and never
    inspected the cached mutation. Fixed to ``settings.default_company``.
    """

    def test_does_not_crash_on_settings_company_field(self):
        """The helper must read a real settings field, so the result never
        carries the swallowed AttributeError signature."""
        result = debug_single_mutation(123)
        self.assertIsInstance(result, dict)
        self.assertNotIn("has no attribute 'company'", str(result.get("error", "")))

    def test_progresses_past_settings_to_downstream_logic(self):
        """With the field fixed, the function reaches the cost-center / mutation-
        cache logic -- any failure is now a legitimate downstream reason, not the
        settings AttributeError."""
        result = debug_single_mutation(123)
        # No cached mutation 123 on the test site, so success is False, but the
        # error must be a downstream one (cost center / cache / not-in-cache),
        # proving the settings lookup itself succeeded.
        if not result["success"]:
            self.assertRegex(
                str(result.get("error", "")),
                r"cost center|mutations cached|not in cache",
            )


if __name__ == "__main__":
    unittest.main()
