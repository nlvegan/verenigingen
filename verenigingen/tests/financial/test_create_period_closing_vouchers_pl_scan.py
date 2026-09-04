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
from verenigingen.tests.support.test_accounts import make_leaf_account, make_submitted_journal_entry


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

    def test_scan_reports_income_and_expense_accounts_not_just_cogs(self):
        from scripts.migration.create_period_closing_vouchers import _check_p_and_l_impact

        income_account = make_leaf_account(
            self.company, self.abbr, "PCV Scan Income",
            account_type="Income Account", root_type="Income",
        )
        expense_account = make_leaf_account(
            self.company, self.abbr, "PCV Scan Expense",
            account_type="Expense Account", root_type="Expense",
        )
        self.track_doc("Account", income_account)
        self.track_doc("Account", expense_account)
        for je in (
            make_submitted_journal_entry(self.company, self.cash_account, income_account, 123.45),
            make_submitted_journal_entry(self.company, expense_account, self.cash_account, 67.89),
        ):
            self.track_doc("Journal Entry", je.name)

        report = _check_p_and_l_impact(self.company)

        # The company is a shared fixture, so other tests' balances may also
        # show up in the totals -- assert on these two accounts' own lines
        # rather than on the report-wide totals.
        self.assertIn(f"{income_account}: -123.45 (Income)", report)
        self.assertIn(f"{expense_account}: 67.89 (Expense)", report)
