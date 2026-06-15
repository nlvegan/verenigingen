"""
Unit / characterization tests for
verenigingen/e_boekhouden/utils/eboekhouden_migration_enhancements.py

Most of EnhancedAccountMigration's value lives in pure type-detection helpers
(_determine_balance_sheet_type, _determine_type_by_code,
_get_root_type_for_account_type, _get_group_name) and the transaction-pattern
analyzer (_analyze_transaction_pattern). These need no DB and no live
eBoekhouden HTTP connection, so we exercise them directly.

The whitelisted run_enhanced_migration() is also covered (it is a thin
orchestrator that currently returns a zeroed result structure).

Run with:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_enhancements
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_migration_enhancements import (
    EnhancedAccountMigration,
    EnhancedTransactionMigration,
    run_enhanced_migration,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _StubMigrationDoc:
    """Minimal stand-in for an E-Boekhouden Migration doc.

    EnhancedAccountMigration only reads .company off the migration doc inside
    the pure helpers under test, so a tiny stub keeps these tests fast and
    DB-free.
    """

    def __init__(self, company="_Test Company 2"):
        self.company = company


def _make_migrator(company="_Test Company 2"):
    return EnhancedAccountMigration(_StubMigrationDoc(company))


class TestDetermineRootTypeForAccountType(unittest.TestCase):
    """_get_root_type_for_account_type maps ERPNext account_type -> root_type."""

    def setUp(self):
        self.m = _make_migrator()

    def test_known_asset_types(self):
        for at in ("Bank", "Cash", "Receivable", "Fixed Asset", "Current Asset"):
            self.assertEqual(self.m._get_root_type_for_account_type(at), "Asset")

    def test_known_liability_types(self):
        for at in ("Payable", "Current Liability", "Tax"):
            self.assertEqual(self.m._get_root_type_for_account_type(at), "Liability")

    def test_expense_and_income(self):
        self.assertEqual(self.m._get_root_type_for_account_type("Expense"), "Expense")
        self.assertEqual(self.m._get_root_type_for_account_type("Income"), "Income")

    def test_unknown_type_defaults_to_asset(self):
        self.assertEqual(self.m._get_root_type_for_account_type("Nonsense"), "Asset")


class TestDetermineBalanceSheetType(unittest.TestCase):
    """_determine_balance_sheet_type: code/name based BAL classification."""

    def setUp(self):
        self.m = _make_migrator()

    def test_fixed_asset_by_code_prefix_02(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "0201", "description": "Gebouwen"})
        self.assertEqual((at, rt), ("Fixed Asset", "Asset"))

    def test_fixed_asset_by_name_keyword(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "0999", "description": "Vaste activa post"})
        self.assertEqual((at, rt), ("Fixed Asset", "Asset"))

    def test_cash_when_kas_in_name(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "1000", "description": "Kas"})
        self.assertEqual((at, rt), ("Cash", "Asset"))

    def test_bank_when_code_10_not_kas(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "1010", "description": "Rabobank"})
        self.assertEqual((at, rt), ("Bank", "Asset"))

    def test_receivable_when_13_and_keyword(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "1300", "description": "Debiteuren handel"})
        self.assertEqual((at, rt), ("Receivable", "Asset"))

    def test_current_asset_when_13_without_receivable_keyword(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "1300", "description": "Overlopende activa"})
        self.assertEqual((at, rt), ("Current Asset", "Asset"))

    def test_current_asset_when_14(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "1400", "description": "Voorraad"})
        self.assertEqual((at, rt), ("Current Asset", "Asset"))

    def test_other_1x_defaults_current_asset(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "1900", "description": "Iets"})
        self.assertEqual((at, rt), ("Current Asset", "Asset"))

    def test_equity_when_code_5(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "5000", "description": "Eigen vermogen"})
        self.assertEqual((at, rt), ("", "Equity"))

    def test_current_liability_when_2(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "2000", "description": "Crediteuren"})
        self.assertEqual((at, rt), ("Current Liability", "Liability"))

    def test_default_asset_when_unrecognized(self):
        at, rt = self.m._determine_balance_sheet_type({"code": "9999", "description": "?"})
        self.assertEqual((at, rt), ("", "Asset"))


class TestDetermineTypeByCode(unittest.TestCase):
    """_determine_type_by_code: fallback classification by leading digits."""

    def setUp(self):
        self.m = _make_migrator()

    def test_empty_code_defaults_asset(self):
        self.assertEqual(self.m._determine_type_by_code(""), ("", "Asset"))

    def test_kas_10000_is_cash(self):
        self.assertEqual(self.m._determine_type_by_code("10000"), ("Cash", "Asset"))

    def test_other_10_is_bank(self):
        self.assertEqual(self.m._determine_type_by_code("10100"), ("Bank", "Asset"))

    def test_13_receivable_with_keyword(self):
        at, rt = self.m._determine_type_by_code("13000", {"description": "Debiteuren"})
        self.assertEqual((at, rt), ("Receivable", "Asset"))

    def test_13_current_asset_without_keyword(self):
        at, rt = self.m._determine_type_by_code("13000", {"description": "Iets anders"})
        self.assertEqual((at, rt), ("Current Asset", "Asset"))

    def test_44_payable_with_keyword(self):
        at, rt = self.m._determine_type_by_code("44000", {"description": "Crediteuren"})
        self.assertEqual((at, rt), ("Payable", "Liability"))

    def test_44_current_liability_without_keyword(self):
        at, rt = self.m._determine_type_by_code("44000", {"description": "Overig"})
        self.assertEqual((at, rt), ("Current Liability", "Liability"))

    def test_5_is_equity(self):
        self.assertEqual(self.m._determine_type_by_code("50000"), ("", "Equity"))

    def test_8_is_income(self):
        self.assertEqual(self.m._determine_type_by_code("80000"), ("", "Income"))

    def test_6_and_7_are_expense(self):
        self.assertEqual(self.m._determine_type_by_code("60000"), ("", "Expense"))
        self.assertEqual(self.m._determine_type_by_code("70000"), ("", "Expense"))

    def test_unrecognized_defaults_asset(self):
        self.assertEqual(self.m._determine_type_by_code("99999"), ("", "Asset"))

    def test_account_data_not_dict_is_tolerated(self):
        # name lookup guards isinstance(account_data, dict); a non-dict must not crash
        at, rt = self.m._determine_type_by_code("13000", "not a dict")
        self.assertEqual((at, rt), ("Current Asset", "Asset"))


class TestGetGroupName(unittest.TestCase):
    """_get_group_name: lookup table with a fallback."""

    def setUp(self):
        self.m = _make_migrator()

    def test_known_group_codes(self):
        self.assertEqual(self.m._get_group_name("004"), "Vorderingen - Receivables")
        self.assertEqual(self.m._get_group_name("006"), "Schulden - Liabilities")

    def test_unknown_group_code_returns_fallback(self):
        # Regression: the fallback was a literal "Group {group_code}" (missing the
        # f-prefix); it now interpolates the actual group code.
        self.assertEqual(self.m._get_group_name("ZZZ"), "Group ZZZ")


class TestAnalyzeTransactionPattern(unittest.TestCase):
    """_analyze_transaction_pattern: bank + (receivable|payable) => 'payment'."""

    def setUp(self):
        self.m = EnhancedTransactionMigration(_StubMigrationDoc())

    def _groups(self, *codes):
        # account_groups maps (ledgerId, accountCode) -> [transactions]
        return {(i, code): [{}] for i, code in enumerate(codes)}

    def test_bank_plus_receivable_is_payment(self):
        groups = self._groups("10100", "13000")
        self.assertEqual(self.m._analyze_transaction_pattern(groups), "payment")

    def test_bank_plus_payable_is_payment(self):
        groups = self._groups("10100", "44000")
        self.assertEqual(self.m._analyze_transaction_pattern(groups), "payment")

    def test_bank_only_is_standard(self):
        groups = self._groups("10100", "80000")
        self.assertEqual(self.m._analyze_transaction_pattern(groups), "standard")

    def test_kas_10000_is_not_bank(self):
        # 10000 (Kas) is explicitly excluded from the bank detection
        groups = self._groups("10000", "13000")
        self.assertEqual(self.m._analyze_transaction_pattern(groups), "standard")

    def test_no_codes_is_standard(self):
        groups = {(0, None): [{}]}
        self.assertEqual(self.m._analyze_transaction_pattern(groups), "standard")


class TestDetermineAccountTypeFallback(unittest.TestCase):
    """_determine_account_type uses the category map when smart-typing is absent.

    get_smart_account_type may or may not import successfully in the test env;
    either way the function must return a (account_type, root_type) tuple.
    """

    def setUp(self):
        self.m = _make_migrator()

    def test_returns_tuple_for_fin_category(self):
        # FIN + code "10100": a bank account (code starts "10", not "10000"/kas)
        # resolves deterministically to ("Bank", "Asset").
        result = self.m._determine_account_type({"category": "FIN", "code": "10100"})
        self.assertEqual(result, ("Bank", "Asset"))

    def test_bal_category_routes_to_balance_sheet_logic(self):
        # BAL + code "0201" (a 02xx fixed-asset code, "Pand"/building) must
        # classify as a fixed asset deterministically.
        result = self.m._determine_account_type({"category": "BAL", "code": "0201", "description": "Pand"})
        self.assertEqual(result, ("Fixed Asset", "Asset"))

    def test_unknown_category_falls_back_to_code(self):
        # Unknown category falls through to code-range logic; "80000" is an
        # income account (8xxxx) -> ("Income Account", "Income").
        result = self.m._determine_account_type({"category": "ZZZ", "code": "80000"})
        self.assertEqual(result, ("Income Account", "Income"))


class TestRunEnhancedMigration(EnhancedTestCase):
    """run_enhanced_migration: whitelisted orchestrator (callable as plain fn)."""

    def test_missing_migration_returns_error(self):
        result = run_enhanced_migration("NON-EXISTENT-MIGRATION-XYZ")
        self.assertFalse(result["success"])
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
