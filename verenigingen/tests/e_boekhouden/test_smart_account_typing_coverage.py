"""
Coverage sweep for eboekhouden_smart_account_typing.py

Target: verenigingen/e_boekhouden/utils/eboekhouden_smart_account_typing.py

LIVENESS: LIVE. get_smart_account_type() is reached from the active migration
flow: AccountMigrationService.create_account(use_enhanced=True) ->
eboekhouden_migration_enhancements.EnhancedAccountTypeDeterminer ->
get_smart_account_type. The E-Boekhouden Migration DocType delegates
create_account(..., use_enhanced=use_enhanced) to that service.

Testable surface (PURE function, no DB / no HTTP):
- get_smart_account_type(account_data) -> (account_type, root_type)

The function maps a Dutch RGS-style account code + description + category to an
ERPNext (account_type, root_type) pair. Every branch is exercised here with a
behaviour assertion that would FAIL if the mapping logic regressed.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_smart_account_typing_coverage
"""

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_smart_account_typing import get_smart_account_type
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _data(code="", description="", category=""):
    return {"code": code, "description": description, "category": category}


class TestSmartAccountTypingReceivable(EnhancedTestCase):
    """13xxx / debiteuren -> Receivable; non-receivable 13xxx -> Current Asset."""

    def test_trade_debtors_130_prefix(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="13000")), ("Receivable", "Asset"))

    def test_amounts_to_be_received_139_prefix(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="13900")), ("Receivable", "Asset"))

    def test_handelsdebiteuren_description(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="13500", description="Handelsdebiteuren binnenland")),
                ("Receivable", "Asset"),
            )

    def test_13xxx_receivable_keyword_in_description(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="13500", description="Nog te ontvangen bedragen")),
                ("Receivable", "Asset"),
            )

    def test_13xxx_without_receivable_keyword_is_current_asset(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="13500", description="Overige posten")),
                ("Current Asset", "Asset"),
            )

    def test_debiteuren_in_description_without_13_code(self):
        # "debiteuren" anywhere triggers the receivable branch even without a 13 code.
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="22000", description="Diverse debiteuren")),
                ("Receivable", "Asset"),
            )


class TestSmartAccountTypingPayable(EnhancedTestCase):
    """44xxx / crediteuren -> Payable; non-payable 44xxx -> Current Liability."""

    def test_trade_creditors_440_prefix(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="44000")), ("Payable", "Liability"))

    def test_amounts_to_be_paid_449_prefix(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="44900")), ("Payable", "Liability"))

    def test_handelscrediteuren_description(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="44500", description="Handelscrediteuren")),
                ("Payable", "Liability"),
            )

    def test_44xxx_payable_keyword_in_description(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="44500", description="Nog te betalen kosten")),
                ("Payable", "Liability"),
            )

    def test_44xxx_without_payable_keyword_is_current_liability(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="44500", description="Overige schulden post")),
                ("Current Liability", "Liability"),
            )


class TestSmartAccountTypingOtherRanges(EnhancedTestCase):
    """12xxx, 45/46xxx, 10xxx, 0xxx, 3xxx ranges."""

    def test_12xxx_receivable_when_keyword(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="12100", description="Vordering op personeel")),
                ("Receivable", "Asset"),
            )

    def test_12xxx_current_asset_otherwise(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="12100", description="Vooruitbetaald")),
                ("Current Asset", "Asset"),
            )

    def test_45xxx_payable_when_keyword(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="45000", description="Te betalen sociale lasten")),
                ("Payable", "Liability"),
            )

    def test_46xxx_current_liability_otherwise(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="46000", description="Diverse posten")),
                ("Current Liability", "Liability"),
            )

    def test_10000_is_cash(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="10000")), ("Cash", "Asset"))

    def test_kas_description_is_cash(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="10100", description="Kas euro")), ("Cash", "Asset")
            )

    def test_10xxx_non_cash_is_bank(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="10200", description="ING rekening")), ("Bank", "Asset")
            )

    def test_0xxx_is_fixed_asset(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="0100")), ("Fixed Asset", "Asset"))

    def test_3xxx_is_stock(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="30000")), ("Stock", "Asset"))

    def test_voorraad_description_is_stock(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="29000", description="Voorraad goederen")),
                ("Stock", "Asset"),
            )


class TestSmartAccountTypingEquityIncomeExpense(EnhancedTestCase):
    """5xxx equity (+ FIN mismatch log), 8/9 income, 4/6/7 expense, tax."""

    def test_5xxx_is_equity(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="50000")), ("Equity", "Equity"))

    def test_5xxx_with_fin_category_logs_mismatch_and_returns_equity(self):
        # The FIN-on-equity branch logs an Error Log on purpose; mark it expected so
        # the automatic tearDown guard does not fail, then assert the log WAS written
        # with the interpolated code/description (regression guard for the f-string
        # fix: the old plain-string log emitted the literal "{code}" placeholder and
        # never substituted the account code).
        self.expectErrorLog("eBoekhouden Category Mismatch")
        marker = frappe.utils.now_datetime()
        result = get_smart_account_type(
            _data(code="50000", description="Aandelenkapitaal", category="FIN")
        )
        self.assertEqual(result, ("Equity", "Equity"))
        # On this Frappe, frappe.log_error(message, title) stores the title in the
        # Error Log "error" field and the message in "method".
        logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", marker], "error": "eBoekhouden Category Mismatch"},
            fields=["method"],
            limit=1,
        )
        self.assertTrue(logs, "expected an 'eBoekhouden Category Mismatch' Error Log")
        # The interpolated message must contain the real code, not the literal "{code}".
        self.assertIn("50000", logs[0].method or "")
        self.assertNotIn("{code}", logs[0].method or "")

    def test_eig_category_is_equity(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="", category="EIG")), ("Equity", "Equity")
            )

    def test_8xxx_is_income(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="80000")), ("Income Account", "Income"))

    def test_9xxx_is_income(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="90000")), ("Income Account", "Income"))

    def test_6xxx_is_expense(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="60000")), ("Expense Account", "Expense"))

    def test_40xxx_expense_not_creditor(self):
        # 4xxx is expense EXCEPT 44xxx (creditors). 40xxx must be expense.
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="40000")), ("Expense Account", "Expense"))

    def test_btw_description_is_tax(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="", description="BTW te betalen hoog")),
                ("Tax", "Liability"),
            )


class TestSmartAccountTypingFallbacks(EnhancedTestCase):
    """Category-map fallback and code-first-digit fallback and ultimate default."""

    def test_category_map_deb(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="", category="DEB")), ("Receivable", "Asset")
            )

    def test_category_map_vw_is_expense(self):
        with self.assertNoErrorLog():
            self.assertEqual(
                get_smart_account_type(_data(code="", category="VW")), ("Expense Account", "Expense")
            )

    def test_first_digit_fallback_2_is_current_asset(self):
        # code "20000" with no matching range/keyword/category -> first-digit fallback.
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data(code="20000")), ("Current Asset", "Asset"))

    def test_ultimate_fallback_empty_everything(self):
        with self.assertNoErrorLog():
            self.assertEqual(get_smart_account_type(_data()), ("Current Asset", "Asset"))
