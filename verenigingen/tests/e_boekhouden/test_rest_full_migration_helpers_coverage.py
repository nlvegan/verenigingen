"""
Coverage sweep for currently-uncovered PURE / DB-testable helpers in
verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py

Complements (and does NOT duplicate):
  - test_migration_pure_helpers.py
  - test_rest_migration_helpers.py

Both of those already cover: _calculate_opening_balance_debit_credit,
_categorize_batch_errors, _detect_credit_note_improved,
_convert_regels_for_credit_note, _convert_mutation_detail_amount,
should_skip_mutation, _convert_negative_amounts_to_positive,
_convert_regels_for_sales_credit_note, _resolve_account_mapping,
ensure_account_type_is_correct, _classify_opening_balance_account,
_add_opening_balance_balancing_entry, create_invoice_line_for_tegenrekening,
migration_status_summary, get_mutation_gap_report, analyze_import_failures.

This file targets the *remaining* helpers:
  - _check_if_already_imported           (DB lookup by mutation_nr)
  - _check_if_invoice_number_exists      (DB lookup + None short-circuit)
  - _get_memorial_booking_amounts        (pure debit/credit convention)
  - _get_bank_transaction_stats          (DB aggregate + branch formatting)
  - _retry_transient_failures            (no-retry / non-transient branches)
  - _finalize_mutation_savepoint         (savepoint release / tolerant failure)
  - _validate_memorial_booking           (balance assertion / raise paths)

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_full_migration_helpers_coverage
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _check_if_already_imported,
    _check_if_invoice_number_exists,
    _finalize_mutation_savepoint,
    _get_bank_transaction_stats,
    _get_memorial_booking_amounts,
    _retry_transient_failures,
    _validate_memorial_booking,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


# ---------------------------------------------------------------------------
# Pure: _get_memorial_booking_amounts
# ---------------------------------------------------------------------------
class TestGetMemorialBookingAmounts(unittest.TestCase):
    """The 'amount' field is the CREDIT side: positive => credit row / debit main."""

    def test_positive_amount_credits_row_debits_main(self):
        debug = []
        row_debit, row_credit, main_debit, main_credit = _get_memorial_booking_amounts(
            "1001", "2002", 8445.03, debug
        )
        self.assertEqual(row_debit, 0)
        self.assertEqual(row_credit, 8445.03)
        self.assertEqual(main_debit, 8445.03)
        self.assertEqual(main_credit, 0)

    def test_negative_amount_debits_row_credits_main(self):
        debug = []
        row_debit, row_credit, main_debit, main_credit = _get_memorial_booking_amounts(
            "1001", "2002", -250.0, debug
        )
        self.assertEqual(row_debit, 250.0)
        self.assertEqual(row_credit, 0)
        self.assertEqual(main_debit, 0)
        self.assertEqual(main_credit, 250.0)

    def test_zero_amount_goes_to_negative_branch_all_zero(self):
        # row_amount > 0 is False for 0 => negative branch, abs(0)=0 everywhere.
        debug = []
        row_debit, row_credit, main_debit, main_credit = _get_memorial_booking_amounts(
            "1001", "2002", 0, debug
        )
        self.assertEqual((row_debit, row_credit, main_debit, main_credit), (0, 0, 0, 0))

    def test_each_side_balances(self):
        """Row total and main total are always equal and opposite (a balanced pair)."""
        for amount in (123.45, -67.89, 1000.0, -0.01):
            rd, rc, md, mc = _get_memorial_booking_amounts("a", "b", amount, [])
            # row net (debit-credit) must be the exact inverse of main net
            self.assertAlmostEqual(rd - rc, -(md - mc), places=2)
            self.assertAlmostEqual(abs(rd - rc), abs(amount), places=2)

    def test_debug_info_records_inputs_and_result(self):
        debug = []
        _get_memorial_booking_amounts("L9", "L8", 5.0, debug)
        joined = "\n".join(debug)
        self.assertIn("row_ledger=L9", joined)
        self.assertIn("main_ledger=L8", joined)
        self.assertIn("Memorial amounts", joined)


# ---------------------------------------------------------------------------
# Pure-ish: _retry_transient_failures (no API call when nothing to retry)
# ---------------------------------------------------------------------------
class TestRetryTransientFailures(unittest.TestCase):
    """The retry loop only runs for transient-pattern errors carrying a mutation id.

    When failed==0, or no error matches a transient pattern, the function returns
    the counts unchanged and retry_summary is None -- and crucially never calls
    import_single_mutation (no live API needed).
    """

    def test_no_failures_returns_unchanged_no_summary(self):
        debug = []
        result = _retry_transient_failures("MIG-1", errors=[], failed=0, imported=10, debug_info=debug)
        self.assertEqual(result["imported"], 10)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["errors"], [])
        self.assertIsNone(result["retry_summary"])
        self.assertEqual(debug, [])

    def test_non_transient_errors_are_not_retried(self):
        debug = []
        errors = ["mutation 42 failed: ValidationError missing account"]
        result = _retry_transient_failures("MIG-1", errors=errors, failed=1, imported=0, debug_info=debug)
        # Permanent error -> nothing retried, counts unchanged, no summary.
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["errors"], errors)
        self.assertIsNone(result["retry_summary"])

    def test_transient_error_without_mutation_id_not_retried(self):
        # Matches a transient pattern but carries no "mutation <id>" => skipped.
        debug = []
        errors = ["Deadlock found when trying to get lock"]
        result = _retry_transient_failures("MIG-1", errors=errors, failed=1, imported=0, debug_info=debug)
        self.assertIsNone(result["retry_summary"])
        self.assertEqual(result["failed"], 1)


# ---------------------------------------------------------------------------
# Pure: _finalize_mutation_savepoint (tolerant of dropped savepoint)
# ---------------------------------------------------------------------------
class TestFinalizeMutationSavepoint(EnhancedTestCase):
    """Release a per-mutation savepoint; a missing one is logged, never raised."""

    def test_release_existing_savepoint_succeeds_silently(self):
        sp = "ebkh_test_sp_ok"
        frappe.db.savepoint(sp)
        debug = []
        # succeeded=True => no rollback, just release. Must not append a warning.
        _finalize_mutation_savepoint(sp, succeeded=True, debug_info=debug)
        self.assertFalse(any("SAVEPOINT WARNING" in m for m in debug))

    def test_rollback_then_release_on_failure(self):
        sp = "ebkh_test_sp_fail"
        frappe.db.savepoint(sp)
        debug = []
        # succeeded=False => rollback to savepoint, then release; no warning.
        _finalize_mutation_savepoint(sp, succeeded=False, debug_info=debug)
        self.assertFalse(any("SAVEPOINT WARNING" in m for m in debug))

    def test_missing_savepoint_is_tolerated_and_logged(self):
        debug = []
        # Never created -> release raises internally -> caught, warning appended,
        # and the function returns normally (does not abort the batch).
        _finalize_mutation_savepoint("ebkh_never_created_sp", succeeded=True, debug_info=debug)
        self.assertTrue(any("SAVEPOINT WARNING" in m for m in debug))
        self.assertTrue(any("ebkh_never_created_sp" in m for m in debug))


# ---------------------------------------------------------------------------
# DB: _check_if_already_imported / _check_if_invoice_number_exists
# ---------------------------------------------------------------------------
class TestCheckIfAlreadyImported(EnhancedTestCase):
    """Lookup helpers that gate re-import by mutation_nr / invoice number."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def _make_draft_je_with_mutation_nr(self, mutation_nr, invoice_number=None):
        """Persist a minimal DRAFT Journal Entry tagged with eBoekhouden fields.

        The lookup helpers only read the tag columns (no docstatus filter), so a
        draft JE is sufficient and avoids submission/FY requirements.
        """
        account = frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 0}, "name"
        )
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = frappe.utils.today()
        je.eboekhouden_mutation_nr = str(mutation_nr)
        if invoice_number is not None and frappe.db.has_column(
            "Journal Entry", "eboekhouden_invoice_number"
        ):
            je.eboekhouden_invoice_number = str(invoice_number)
        je.append(
            "accounts",
            {"account": account, "debit_in_account_currency": 0, "credit_in_account_currency": 0},
        )
        je.flags.ignore_validate = True
        je.flags.ignore_mandatory = True
        je.insert(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc("Journal Entry", je.name, force=True))
        return je.name

    def test_unknown_mutation_returns_none(self):
        with self.assertNoErrorLog():
            self.assertIsNone(_check_if_already_imported("ebkh-no-such-9999999", "Journal Entry"))

    def test_known_mutation_returns_docname(self):
        mutation_nr = "ebkh-cov-mut-7777001"
        je_name = self._make_draft_je_with_mutation_nr(mutation_nr)
        with self.assertNoErrorLog():
            found = _check_if_already_imported(mutation_nr, "Journal Entry")
        self.assertEqual(found, je_name)

    def test_mutation_nr_coerced_to_string(self):
        """An int mutation id matches a row stored as the string form."""
        mutation_nr = 7777002
        je_name = self._make_draft_je_with_mutation_nr(mutation_nr)
        # Pass the int; helper str()-casts before the lookup.
        found = _check_if_already_imported(mutation_nr, "Journal Entry")
        self.assertEqual(found, je_name)

    def test_invoice_number_none_short_circuits(self):
        # Falsy invoice_number returns None WITHOUT querying the DB.
        self.assertIsNone(_check_if_invoice_number_exists(None, "Journal Entry"))
        self.assertIsNone(_check_if_invoice_number_exists("", "Journal Entry"))

    def test_invoice_number_unknown_returns_none(self):
        if not frappe.db.has_column("Journal Entry", "eboekhouden_invoice_number"):
            self.skipTest("eboekhouden_invoice_number not present on Journal Entry")
        with self.assertNoErrorLog():
            self.assertIsNone(
                _check_if_invoice_number_exists("ebkh-no-such-inv-9999999", "Journal Entry")
            )

    def test_invoice_number_known_returns_docname(self):
        if not frappe.db.has_column("Journal Entry", "eboekhouden_invoice_number"):
            self.skipTest("eboekhouden_invoice_number not present on Journal Entry")
        invoice_number = "ebkh-cov-inv-7777003"
        je_name = self._make_draft_je_with_mutation_nr("ebkh-cov-mut-7777003", invoice_number)
        found = _check_if_invoice_number_exists(invoice_number, "Journal Entry")
        self.assertEqual(found, je_name)


# ---------------------------------------------------------------------------
# DB: _get_bank_transaction_stats (branch-rich string builder)
# ---------------------------------------------------------------------------
class TestGetBankTransactionStats(EnhancedTestCase):
    """Builds a stats block from Payment Entry / Bank Transaction Payments rows."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def _make_payment_entry(self, mutation_nr):
        """Persist a DRAFT internal-transfer Payment Entry tagged with mutation_nr.

        Internal transfer avoids party/account-type requirements. The stats SQL
        only filters on eboekhouden_mutation_nr with no docstatus filter, so a
        draft PE is counted exactly like a submitted one.
        """
        bank = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": "Bank", "is_group": 0}, "name"
        ) or frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 0}, "name"
        )
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Internal Transfer"
        pe.company = self.company
        pe.posting_date = frappe.utils.today()
        pe.paid_from = bank
        pe.paid_to = bank
        pe.paid_amount = 1
        pe.received_amount = 1
        pe.eboekhouden_mutation_nr = str(mutation_nr)
        pe.flags.ignore_validate = True
        pe.flags.ignore_mandatory = True
        pe.insert(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc("Payment Entry", pe.name, force=True))
        return pe.name

    def test_empty_mutations_returns_empty_string(self):
        self.assertEqual(_get_bank_transaction_stats([], "Customer Payments"), "")
        self.assertEqual(_get_bank_transaction_stats(None, "Customer Payments"), "")

    def test_no_payment_entries_reports_all_journal_entries_branch(self):
        """Mutations with NO matching Payment Entry => total==0 branch."""
        mutations = [{"id": "ebkh-cov-bt-none-1"}, {"id": "ebkh-cov-bt-none-2"}]
        result = _get_bank_transaction_stats(mutations, "Money Received")
        self.assertIn("PAYMENT ENTRY STATUS:", result)
        self.assertIn("No Payment Entries created (2 mutations processed)", result)
        self.assertIn("All 2 mutations created as Journal Entries instead", result)

    def test_payment_entries_present_reports_bank_transaction_branch(self):
        """A matching Payment Entry (no Bank Transaction) => the BANK TRANSACTION
        STATUS branch, with without_bt warning and a JE-count for unmatched ids."""
        pe_mut = "ebkh-cov-bt-pe-1"
        self._make_payment_entry(pe_mut)
        # 3 mutations, only 1 has a Payment Entry => je_count == 2.
        mutations = [{"id": pe_mut}, {"id": "ebkh-cov-bt-je-1"}, {"id": "ebkh-cov-bt-je-2"}]
        result = _get_bank_transaction_stats(mutations, "Customer Payments")
        self.assertIn("BANK TRANSACTION STATUS:", result)
        self.assertIn("Payment Entries in batch: 1 (of 3 mutations)", result)
        self.assertIn("Created as Payment Entry: 1", result)
        self.assertIn("Created as Journal Entry instead: 2", result)
        # No Bank Transaction Payments row links to it => 0 with, 1 without.
        self.assertIn("With Bank Transactions: 0 (0.0%)", result)
        self.assertIn("WITHOUT Bank Transactions: 1", result)
        self.assertIn("WARNING: 1 Payment Entries missing Bank Transactions!", result)


# ---------------------------------------------------------------------------
# DB: _validate_memorial_booking (balance check)
# ---------------------------------------------------------------------------
class TestValidateMemorialBooking(EnhancedTestCase):
    """Raises when the JE debit/credit totals are imbalanced beyond 0.01."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.cost_center = frappe.db.get_value(
            "Cost Center", {"company": cls.company, "is_group": 0}, "name"
        )

    def _new_je(self):
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        return je

    def _balanced_rows(self, amount):
        """A single memorial row whose net matches `amount` (passes row validation)."""
        return [{"ledgerId": 1, "amount": amount}]

    def test_imbalanced_totals_raise(self):
        """Row amounts sum correctly but debit != credit => balance Exception."""
        je = self._new_je()
        amount = 100.0
        with self.assertRaises(Exception) as ctx:
            _validate_memorial_booking(
                je,
                mutation={"id": 555, "amount": amount},
                rows=self._balanced_rows(amount),
                amount=amount,
                total_debit=100.0,
                total_credit=50.0,  # deliberate imbalance
                company=self.company,
                cost_center=self.cost_center,
                debug_info=[],
            )
        self.assertIn("not balanced", str(ctx.exception))

    def test_balanced_within_tolerance_does_not_raise(self):
        """debit == credit (within 0.01) and rows sum correctly => no raise."""
        je = self._new_je()
        amount = 100.0
        debug = []
        # Should return None and append a "balanced" debug line.
        _validate_memorial_booking(
            je,
            mutation={"id": 556, "amount": amount},
            rows=self._balanced_rows(amount),
            amount=amount,
            total_debit=100.0,
            total_credit=100.005,  # within 0.01 tolerance
            company=self.company,
            cost_center=self.cost_center,
            debug_info=debug,
        )
        self.assertTrue(any("is balanced" in m for m in debug))


if __name__ == "__main__":
    unittest.main()
