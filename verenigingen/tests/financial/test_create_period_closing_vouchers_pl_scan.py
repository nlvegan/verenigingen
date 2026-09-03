#!/usr/bin/env python3
"""
#789: ``check_p_and_l_impact`` (scripts/migration/create_period_closing_vouchers.py)
filtered on ``acc.account_type IN ('Income', 'Expense', 'Cost of Goods Sold')``.
Of those three literals, only "Cost of Goods Sold" is a valid
``Account.account_type`` option -- "Income" and "Expense" are
``Account.root_type`` values instead. So the P&L-imbalance scan silently
missed every Income and Expense account and only ever reported on COGS
accounts.

This test creates its own fresh, zero-balance Income and Expense accounts
(so the assertions don't depend on whatever balance other tests have left on
the company's stock accounts), posts real GL Entries against them, and
asserts the scan's report actually surfaces them.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPeriodClosingVouchersPLScan(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        cls.company = get_eur_test_company()
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")
        cls.cash_account = f"Cash - {cls.abbr}"
        if not frappe.db.exists("Account", cls.cash_account):
            raise RuntimeError(f"Expected seeded account {cls.cash_account!r} not found on {cls.company}")

    def _make_account(self, account_name, *, account_type, root_type):
        """Create a fresh, zero-balance leaf Account with an account_type that
        is NOT one of the three literals the buggy query pinned ("Income",
        "Expense", "Cost of Goods Sold")."""
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": root_type, "is_group": 1}, "name"
        )
        doc = frappe.new_doc("Account")
        doc.account_name = account_name
        doc.company = self.company
        doc.parent_account = parent
        doc.root_type = root_type
        doc.account_type = account_type
        doc.is_group = 0
        doc.insert(ignore_permissions=True)
        self.track_doc("Account", doc.name)
        return doc.name

    def _make_je(self, debit_account, credit_account, amount):
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = today()
        je.append(
            "accounts",
            {"account": debit_account, "debit_in_account_currency": amount, "credit_in_account_currency": 0},
        )
        je.append(
            "accounts",
            {"account": credit_account, "debit_in_account_currency": 0, "credit_in_account_currency": amount},
        )
        je.insert(ignore_permissions=True)
        je.submit()
        self.track_doc("Journal Entry", je.name)
        return je

    def test_scan_reports_income_and_expense_accounts_not_just_cogs(self):
        from scripts.migration.create_period_closing_vouchers import _check_p_and_l_impact

        income_account = self._make_account(
            "PCV Scan Income", account_type="Income Account", root_type="Income"
        )
        expense_account = self._make_account(
            "PCV Scan Expense", account_type="Expense Account", root_type="Expense"
        )
        self._make_je(self.cash_account, income_account, 123.45)
        self._make_je(expense_account, self.cash_account, 67.89)

        report = _check_p_and_l_impact(self.company)

        # The company is a shared fixture, so other tests' balances may also
        # show up in the totals -- assert on these two accounts' own lines
        # rather than on the report-wide totals.
        self.assertIn(f"{income_account}: -123.45 (Income)", report)
        self.assertIn(f"{expense_account}: 67.89 (Expense)", report)
