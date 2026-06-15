"""
Characterization / unit tests for helper functions in
verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py

These complement test_migration_pure_helpers.py (which already covers
_calculate_opening_balance_debit_credit, _categorize_batch_errors,
_detect_credit_note_improved, _convert_regels_for_credit_note,
_convert_mutation_detail_amount).

This file covers additional pure/semi-pure helpers plus a few DB-backed
helpers that can be exercised without a live eBoekhouden API connection.

Run with:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_migration_helpers
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _add_opening_balance_balancing_entry,
    _classify_opening_balance_account,
    _convert_negative_amounts_to_positive,
    _convert_regels_for_sales_credit_note,
    _detect_credit_note_improved,
    _resolve_account_mapping,
    analyze_import_failures,
    create_invoice_line_for_tegenrekening,
    ensure_account_type_is_correct,
    get_mutation_gap_report,
    migration_status_summary,
    should_skip_mutation,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# Pure functions (no DB)
# ---------------------------------------------------------------------------
class TestShouldSkipMutation(unittest.TestCase):
    """should_skip_mutation: only skips invoice mutations flagged as system imports."""

    def test_system_notification_invoice_skipped(self):
        debug = []
        mutation = {"id": 1, "type": 1, "amount": 100, "description": "System Notification of order"}
        self.assertTrue(should_skip_mutation(mutation, debug))
        self.assertTrue(any("Skipping" in m for m in debug))

    def test_status_update_invoice_skipped(self):
        mutation = {"id": 2, "type": 2, "amount": 50, "description": "Order STATUS UPDATE received"}
        self.assertTrue(should_skip_mutation(mutation))

    def test_normal_invoice_not_skipped(self):
        mutation = {"id": 3, "type": 1, "amount": 100, "description": "Regular customer invoice"}
        self.assertFalse(should_skip_mutation(mutation))

    def test_woocommerce_invoice_not_skipped(self):
        # WooCommerce invoices are legitimate and must NOT be skipped.
        mutation = {"id": 4, "type": 1, "amount": 25, "description": "WooCommerce order #1234"}
        self.assertFalse(should_skip_mutation(mutation))

    def test_non_invoice_type_never_skipped(self):
        # Type 5 (money received) with the magic phrase still must not be skipped:
        # the system-pattern rule only applies to invoice types 1 & 2.
        mutation = {"id": 5, "type": 5, "amount": 0, "description": "system notification"}
        self.assertFalse(should_skip_mutation(mutation))

    def test_zero_amount_invoice_not_skipped(self):
        # Zero-amount invoices are valid in ERPNext and should be processed.
        debug = []
        mutation = {"id": 6, "type": 1, "amount": 0, "description": "Free membership"}
        self.assertFalse(should_skip_mutation(mutation, debug))
        # zero-amount path appends a monitoring log entry
        self.assertTrue(any("zero-amount" in m for m in debug))

    def test_missing_fields_defaults(self):
        # Empty mutation: amount defaults to 0, type 0, no crash.
        self.assertFalse(should_skip_mutation({}))


class TestConvertRegelsWrappers(unittest.TestCase):
    """Thin wrappers delegating to _convert_regels_for_credit_note."""

    def test_convert_negative_amounts_to_positive_purchase(self):
        regels = [{"amount": -100.0, "quantity": 2.0}]
        out = _convert_negative_amounts_to_positive(regels, [])
        self.assertEqual(out[0]["amount"], 100.0)
        # Returns (purchase credit note) => quantities must be negative
        self.assertEqual(out[0]["quantity"], -2.0)

    def test_convert_sales_credit_note(self):
        regels = [{"amount": -40.0, "quantity": 1.0}]
        out = _convert_regels_for_sales_credit_note(regels, [])
        self.assertEqual(out[0]["amount"], 40.0)
        self.assertEqual(out[0]["quantity"], -1.0)

    def test_empty_regels_passthrough(self):
        self.assertEqual(_convert_negative_amounts_to_positive([], []), [])
        self.assertEqual(_convert_negative_amounts_to_positive(None, []), None)

    def test_original_not_mutated(self):
        regels = [{"amount": -10.0, "quantity": 3.0}]
        _convert_negative_amounts_to_positive(regels, [])
        # source dict must be untouched (function copies each regel)
        self.assertEqual(regels[0]["amount"], -10.0)
        self.assertEqual(regels[0]["quantity"], 3.0)

    def test_dutch_field_names(self):
        # SOAP-style field names (Prijs/Aantal) are handled too.
        regels = [{"Prijs": -5.0, "Aantal": 4.0}]
        out = _convert_negative_amounts_to_positive(regels, [])
        self.assertEqual(out[0]["Prijs"], 5.0)
        self.assertEqual(out[0]["Aantal"], -4.0)


class TestDetectCreditNoteExtra(unittest.TestCase):
    """Additional edge cases for _detect_credit_note_improved (rows + Regels keys)."""

    def test_main_amount_negative(self):
        is_cn, total = _detect_credit_note_improved({"amount": -200.0}, [])
        self.assertTrue(is_cn)
        self.assertEqual(total, -200.0)

    def test_main_amount_positive(self):
        is_cn, total = _detect_credit_note_improved({"amount": 150.0}, [])
        self.assertFalse(is_cn)
        self.assertEqual(total, 150.0)

    def test_zero_main_all_negative_rows_is_credit_note(self):
        detail = {"amount": 0, "rows": [{"amount": -10, "quantity": 1}, {"amount": -5, "quantity": 1}]}
        is_cn, total = _detect_credit_note_improved(detail, [])
        self.assertTrue(is_cn)
        self.assertEqual(total, -15.0)

    def test_zero_main_mixed_rows_not_credit_note(self):
        detail = {"amount": 0, "rows": [{"amount": -10, "quantity": 1}, {"amount": 30, "quantity": 1}]}
        is_cn, total = _detect_credit_note_improved(detail, [])
        self.assertFalse(is_cn)
        self.assertEqual(total, 20.0)

    def test_zero_main_no_rows_not_credit_note(self):
        is_cn, total = _detect_credit_note_improved({"amount": 0}, [])
        self.assertFalse(is_cn)
        self.assertEqual(total, 0)


# ---------------------------------------------------------------------------
# DB-backed helpers (no live API needed)
# ---------------------------------------------------------------------------
class TestResolveAccountMapping(EnhancedTestCase):
    """_resolve_account_mapping: looks up E-Boekhouden Ledger Mapping by ledger_id."""

    def _persist_ledger_mapping(self, ledger_id, erpnext_account):
        """Create an E-Boekhouden Ledger Mapping row for ``ledger_id``."""
        existing = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}, "name")
        if existing:
            frappe.delete_doc("E-Boekhouden Ledger Mapping", existing, force=True)
        doc = frappe.new_doc("E-Boekhouden Ledger Mapping")
        doc.ledger_id = ledger_id
        doc.ledger_code = str(ledger_id)
        doc.ledger_name = f"Test Ledger {ledger_id}"
        doc.erpnext_account = erpnext_account
        doc.insert(ignore_permissions=True)
        return doc.name

    def test_none_ledger_returns_none(self):
        self.assertIsNone(_resolve_account_mapping(None, []))

    def test_empty_ledger_returns_none(self):
        self.assertIsNone(_resolve_account_mapping("", []))

    def test_unknown_ledger_returns_none_and_logs(self):
        debug = []
        # Use an id extremely unlikely to exist
        self.assertIsNone(_resolve_account_mapping("999999999", debug))
        self.assertTrue(any("No mapping found" in m for m in debug))

    def test_known_ledger_returns_mapped_dict(self):
        """A mapped ledger_id resolves to its account (product ~L646-664)."""
        # Any existing account is fine; the mapper only echoes erpnext_account.
        account = frappe.db.get_value("Account", {"is_group": 0}, "name")
        self.assertIsNotNone(account)
        ledger_id = 987654321
        self._persist_ledger_mapping(ledger_id, account)

        debug = []
        result = _resolve_account_mapping(ledger_id, debug)
        self.assertEqual(result, {"erpnext_account": account, "ledger_id": ledger_id})
        # Successful resolution must NOT emit the "No mapping found" debug line.
        self.assertFalse(any("No mapping found" in m for m in debug))


class TestEnsureAccountTypeIsCorrect(EnhancedTestCase):
    """ensure_account_type_is_correct: report-only by default, can auto-fix."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST EBkh Helpers Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TEHC"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def _persist_account(self, acct_name, account_type, root_type="Asset"):
        parent = frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": root_type, "is_group": 1},
            "name",
        )
        full = f"{acct_name} - TEHC"
        if frappe.db.exists("Account", full):
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = self.company
        doc.parent_account = parent
        doc.account_type = account_type
        doc.root_type = root_type
        doc.insert(ignore_permissions=True)
        return doc.name

    def test_missing_account_returns_false(self):
        debug = []
        self.assertFalse(ensure_account_type_is_correct("No Such Account - TEHC", "Receivable", debug))
        self.assertTrue(any("does not exist" in m for m in debug))

    def test_already_correct_returns_true(self):
        acct = self._persist_account("EBkh Recv Correct", "Receivable")
        debug = []
        self.assertTrue(ensure_account_type_is_correct(acct, "Receivable", debug))
        self.assertTrue(any("already has correct type" in m for m in debug))

    def test_mismatch_report_only_returns_false_and_does_not_modify(self):
        acct = self._persist_account("EBkh Recv Mismatch", "Receivable")
        debug = []
        # auto_fix defaults to False => returns False, account untouched
        self.assertFalse(ensure_account_type_is_correct(acct, "Payable", debug))
        self.assertEqual(frappe.db.get_value("Account", acct, "account_type"), "Receivable")

    def test_mismatch_auto_fix_corrects_type(self):
        acct = self._persist_account("EBkh Recv AutoFix", "Receivable")
        debug = []
        self.assertTrue(ensure_account_type_is_correct(acct, "Payable", debug, auto_fix=True))
        self.assertEqual(frappe.db.get_value("Account", acct, "account_type"), "Payable")


class TestClassifyOpeningBalanceAccount(EnhancedTestCase):
    """_classify_opening_balance_account: decides skip/party for opening balances."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST EBkh OB Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TEOB"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def _persist_account(self, acct_name, account_type, root_type):
        parent = frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": root_type, "is_group": 1},
            "name",
        )
        full = f"{acct_name} - TEOB"
        if frappe.db.exists("Account", full):
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = self.company
        doc.parent_account = parent
        doc.account_type = account_type
        doc.root_type = root_type
        doc.insert(ignore_permissions=True)
        return doc.name

    def test_missing_account_skipped_not_found(self):
        res = _classify_opening_balance_account("Nonexistent - TEOB", self.company, [])
        self.assertTrue(res["skip"])
        self.assertEqual(res["skip_reason"], "not_found")

    def test_pnl_income_account_skipped(self):
        acct = self._persist_account("EBkh OB Income", "", "Income")
        res = _classify_opening_balance_account(acct, self.company, [])
        self.assertTrue(res["skip"])
        self.assertEqual(res["skip_reason"], "pnl")
        self.assertEqual(res["root_type"], "Income")

    def test_expense_account_skipped(self):
        acct = self._persist_account("EBkh OB Expense", "", "Expense")
        res = _classify_opening_balance_account(acct, self.company, [])
        self.assertTrue(res["skip"])
        self.assertEqual(res["skip_reason"], "pnl")

    def test_stock_account_skipped(self):
        acct = self._persist_account("EBkh OB Stock", "Stock", "Asset")
        res = _classify_opening_balance_account(acct, self.company, [])
        self.assertTrue(res["skip"])
        self.assertEqual(res["skip_reason"], "stock")

    def test_plain_asset_not_skipped_no_party(self):
        acct = self._persist_account("EBkh OB Bank", "Bank", "Asset")
        res = _classify_opening_balance_account(acct, self.company, [])
        self.assertFalse(res["skip"])
        self.assertIsNone(res["party_type"])
        self.assertEqual(res["root_type"], "Asset")

    def test_receivable_account_gets_customer_party(self):
        acct = self._persist_account("EBkh OB Recv", "Receivable", "Asset")
        res = _classify_opening_balance_account(acct, self.company, [])
        self.assertFalse(res["skip"])
        self.assertEqual(res["party_type"], "Customer")
        self.assertTrue(res["party"])

    def test_payable_account_gets_supplier_party(self):
        acct = self._persist_account("EBkh OB Pay", "Payable", "Liability")
        res = _classify_opening_balance_account(acct, self.company, [])
        self.assertFalse(res["skip"])
        self.assertEqual(res["party_type"], "Supplier")
        self.assertTrue(res["party"])


class TestAddOpeningBalanceBalancingEntry(EnhancedTestCase):
    """_add_opening_balance_balancing_entry: appends a balancing line to a JE on imbalance."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()
        cls.cost_center = frappe.db.get_value("Cost Center", {"company": cls.company, "is_group": 0}, "name")

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST EBkh Bal Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TEBC"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def _new_je(self):
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        return je

    def test_balanced_je_no_entry_added(self):
        je = self._new_je()
        _add_opening_balance_balancing_entry(je, 1000.0, 1000.0, self.company, self.cost_center, [])
        self.assertEqual(len(je.accounts), 0)

    def test_within_tolerance_no_entry_added(self):
        je = self._new_je()
        _add_opening_balance_balancing_entry(je, 1000.005, 1000.0, self.company, self.cost_center, [])
        self.assertEqual(len(je.accounts), 0)

    def test_debit_excess_adds_credit_balancing_entry(self):
        je = self._new_je()
        _add_opening_balance_balancing_entry(je, 1500.0, 1000.0, self.company, self.cost_center, [])
        self.assertEqual(len(je.accounts), 1)
        line = je.accounts[0]
        self.assertEqual(line.credit_in_account_currency, 500.0)
        self.assertEqual(line.debit_in_account_currency, 0)

    def test_credit_excess_adds_debit_balancing_entry(self):
        je = self._new_je()
        _add_opening_balance_balancing_entry(je, 1000.0, 1500.0, self.company, self.cost_center, [])
        self.assertEqual(len(je.accounts), 1)
        line = je.accounts[0]
        self.assertEqual(line.debit_in_account_currency, 500.0)
        self.assertEqual(line.credit_in_account_currency, 0)


class TestCreateInvoiceLineForTegenrekening(EnhancedTestCase):
    """create_invoice_line_for_tegenrekening delegates to smart_tegenrekening_mapper."""

    def test_no_code_raises_validation_error(self):
        # Smart mapper now raises instead of using a fallback account.
        with self.assertRaises(frappe.ValidationError):
            create_invoice_line_for_tegenrekening(
                tegenrekening_code=None, amount=100, description="X", transaction_type="purchase"
            )


# ---------------------------------------------------------------------------
# Whitelisted reporting helpers (callable as plain functions in tests)
# ---------------------------------------------------------------------------
class TestReportingHelpers(EnhancedTestCase):
    """migration_status_summary / get_mutation_gap_report / analyze_import_failures."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST EBkh Report Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TERC"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def test_migration_status_summary_returns_dict_with_success_key(self):
        # Regression: the cost-center count filters on the optional custom field
        # `eboekhouden_kostenplaats_id`, which is not shipped on every site. The
        # query is now guarded with has_field so the whole status report no longer
        # dies with a MySQL 1054 when the field is absent.
        result = migration_status_summary(company=self.company)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"], msg=result.get("error"))
        summary = result["summary"]
        self.assertEqual(summary["company"], self.company)
        for key in ("accounts", "cost_centers", "journal_entries", "sales_invoices", "purchase_invoices"):
            self.assertIn(key, summary["data_types"])
        # With the field absent, the eBoekhouden cost-center count defaults to 0
        # instead of raising.
        self.assertEqual(summary["data_types"]["cost_centers"]["from_eboekhouden"], 0)

    def test_get_mutation_gap_report_structure(self):
        result = get_mutation_gap_report()
        self.assertTrue(result["success"])
        self.assertIn("gaps", result)
        # If there happen to be imported mutations, coverage_percentage is present.
        if result["gaps"] or result.get("total_imported"):
            self.assertIn("coverage_percentage", result)

    def test_get_mutation_gap_report_closes_a_seeded_gap(self):
        """Seeding a mutation at a currently-missing id closes exactly that gap.

        ``get_mutation_gap_report`` (product ~L1144-1214) scans every
        Journal/Payment/Sales/Purchase mutation_nr on the site, computes the
        [min, max] sequence and reports the missing ids. The report is global
        (not company-scoped) and the test site already holds thousands of
        imported mutations, so a fixed ``gaps == [2]`` assertion is impossible
        here. Instead we assert the real computation: pick an id that is
        currently a gap, seed a Journal Entry carrying that mutation_nr, and
        verify the product removes that id from ``gaps``, drops ``total_gaps``
        by one, raises ``total_imported`` by one, and recomputes
        ``coverage_percentage`` with the exact product formula.
        """
        before = get_mutation_gap_report()
        self.assertTrue(before["success"])
        # Need at least one interior gap strictly between min and max to seed into.
        interior_gaps = [g for g in before["gaps"] if before["min_mutation"] < g < before["max_mutation"]]
        if not interior_gaps:
            self.skipTest("No interior gap available on this site to seed into")
        gap_id = interior_gaps[0]

        je = self._seed_journal_entry_with_mutation_nr(gap_id)
        self.addCleanup(lambda: frappe.delete_doc("Journal Entry", je, force=True))

        after = get_mutation_gap_report()
        self.assertTrue(after["success"])
        # Min/max unchanged because gap_id is strictly interior.
        self.assertEqual(after["min_mutation"], before["min_mutation"])
        self.assertEqual(after["max_mutation"], before["max_mutation"])
        # The seeded id is no longer a gap.
        self.assertNotIn(gap_id, after["gaps"])
        self.assertEqual(after["total_gaps"], before["total_gaps"] - 1)
        self.assertEqual(after["total_imported"], before["total_imported"] + 1)
        # Coverage recomputed with the product's exact formula.
        span = after["max_mutation"] - after["min_mutation"] + 1
        expected_coverage = round(((span - after["total_gaps"]) / span) * 100, 2)
        self.assertEqual(after["coverage_percentage"], expected_coverage)

    def _seed_journal_entry_with_mutation_nr(self, mutation_nr):
        """Create a minimal draft Journal Entry carrying ``eboekhouden_mutation_nr``.

        The gap report's SQL has no docstatus filter and only reads the
        mutation_nr column, so an unsubmitted JE is counted just like a real
        imported one — sufficient to exercise the gap computation.
        """
        bank = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": "Bank", "is_group": 0}, "name"
        ) or frappe.db.get_value("Account", {"company": self.company, "is_group": 0}, "name")
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = frappe.utils.today()
        je.eboekhouden_mutation_nr = str(mutation_nr)
        je.append(
            "accounts", {"account": bank, "debit_in_account_currency": 0, "credit_in_account_currency": 0}
        )
        je.flags.ignore_validate = True
        je.flags.ignore_mandatory = True
        je.insert(ignore_permissions=True)
        return je.name

    def _make_error_log(self, error_text):
        """Factory: persist an Error Log row and schedule its cleanup."""
        err = frappe.new_doc("Error Log")
        err.method = "ebkh-test-closed-book"
        err.error = error_text
        err.insert(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc("Error Log", err.name, force=True))
        return err.name

    def test_analyze_import_failures_structure(self):
        result = analyze_import_failures()
        self.assertIn("closed_book_errors", result)
        self.assertIn("sample_errors", result)
        self.assertIsInstance(result["sample_errors"], list)

    def test_analyze_import_failures_parses_seeded_closed_book_error(self):
        """A seeded closed-book Error Log is found and its mutation fields parsed.

        ``analyze_import_failures`` (product ~L1057-1094) selects recent Error
        Log rows whose ``error`` contains "Books have been closed", then regex-
        extracts ``"date"``, ``"id"`` and ``"type"`` from the JSON-ish payload
        (~L1073-1089). Seed exactly such an error and assert the parsed values.
        """
        # Distinctive values so we can locate our row among any pre-existing ones.
        error_text = (
            "eBoekhouden import failed: Books have been closed for this period. "
            'Mutation payload: {"id": 424242, "date": "2024-07-15", "type": 3, "amount": 99.5}'
        )
        # frappe.db.sql in the product reads committed + in-txn rows, so the row
        # seeded by the factory is visible within this test transaction.
        self._make_error_log(error_text)

        result = analyze_import_failures()
        self.assertGreaterEqual(result["closed_book_errors"], 1)
        parsed = [s for s in result["sample_errors"] if s.get("id") == "424242"]
        self.assertTrue(parsed, msg=f"seeded error not parsed: {result['sample_errors']}")
        sample = parsed[0]
        self.assertEqual(sample["date"], "2024-07-15")
        self.assertEqual(sample["type"], "3")


if __name__ == "__main__":
    unittest.main()
