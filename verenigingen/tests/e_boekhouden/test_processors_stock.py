"""
Tests for the eBoekhouden StockProcessor.

Covers ``e_boekhouden/utils/processors/stock_processor.py``: routing
(``can_process`` for stock mutation types 7/10 and stock-account detection),
ledger->account lookup, stock-account classification, warehouse/item
get-or-create, and the early-return branches of ``process()`` (no rows, no
stock account, zero amount).

Real integration tests against a EUR company. The full Stock Reconciliation
submit path is intentionally not exercised end-to-end because it requires a
fully configured warehouse/item valuation chain plus the
``eboekhouden_mutation_nr`` custom field, which is not present on all test sites;
those branches are flagged in the agent report instead.

Run with:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_processors_stock
"""

import frappe

from verenigingen.e_boekhouden.utils.processors.stock_processor import StockProcessor
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _persist_eur_company():
    """Return a EUR company name, creating a dedicated test company if needed."""
    existing = frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")
    if existing:
        return existing

    company = frappe.new_doc("Company")
    company.company_name = "EBKH EUR Test Co"
    company.abbr = "EETC"
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return company.name


def _setup_stock_account(company):
    """Return an existing Stock account for the company, or None."""
    return frappe.db.get_value(
        "Account", {"company": company, "account_type": "Stock", "is_group": 0}, "name"
    )


def _persist_ledger_mapping(ledger_id, account):
    """Create an E-Boekhouden Ledger Mapping linking a ledger id to an account."""
    if frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}):
        return
    doc = frappe.new_doc("E-Boekhouden Ledger Mapping")
    doc.ledger_id = str(ledger_id)
    doc.ledger_code = f"TEST{ledger_id}"
    doc.ledger_name = f"Test Ledger {ledger_id}"
    doc.erpnext_account = account
    doc.insert(ignore_permissions=True)


class TestStockProcessor(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()
        cls.stock_account = _setup_stock_account(cls.company)

    def _processor(self):
        return StockProcessor(self.company)

    # ---- _is_stock_account ----

    def test_is_stock_account_none(self):
        self.assertFalse(self._processor()._is_stock_account(None))

    def test_is_stock_account_nonexistent(self):
        self.assertFalse(self._processor()._is_stock_account("No Such Account - X"))

    def test_is_stock_account_true_for_stock(self):
        if not self.stock_account:
            self.skipTest("No Stock account configured on this company")
        self.assertTrue(self._processor()._is_stock_account(self.stock_account))

    def test_is_stock_account_false_for_non_stock(self):
        non_stock = frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 0, "root_type": "Expense"}, "name"
        )
        self.assertFalse(self._processor()._is_stock_account(non_stock))

    # ---- _get_account_for_ledger ----

    def test_get_account_for_unknown_ledger(self):
        self.assertIsNone(self._processor()._get_account_for_ledger(99999999))

    def test_get_account_for_mapped_ledger(self):
        if not self.stock_account:
            self.skipTest("No Stock account configured on this company")
        _persist_ledger_mapping(880011, self.stock_account)
        self.assertEqual(self._processor()._get_account_for_ledger(880011), self.stock_account)

    # ---- can_process ----

    def test_cannot_process_non_stock_type(self):
        self.assertFalse(self._processor().can_process({"id": 1, "type": 3}))

    def test_type7_without_stock_account_false(self):
        self.assertFalse(
            self._processor().can_process({"id": 2, "type": 7, "ledgerId": 99999999, "rows": []})
        )

    def test_type7_with_stock_main_ledger_true(self):
        if not self.stock_account:
            self.skipTest("No Stock account configured on this company")
        _persist_ledger_mapping(880012, self.stock_account)
        self.assertTrue(self._processor().can_process({"id": 3, "type": 7, "ledgerId": 880012, "rows": []}))

    def test_type10_with_stock_row_ledger_true(self):
        if not self.stock_account:
            self.skipTest("No Stock account configured on this company")
        _persist_ledger_mapping(880013, self.stock_account)
        self.assertTrue(
            self._processor().can_process(
                {"id": 4, "type": 10, "ledgerId": 99999999, "rows": [{"ledgerId": 880013}]}
            )
        )

    # ---- process() early returns ----

    def test_process_no_rows_returns_none(self):
        result = self._processor().process({"id": 5, "type": 7, "rows": []})
        self.assertIsNone(result)

    def test_process_no_stock_account_returns_none(self):
        # Rows present but none map to a stock account
        result = self._processor().process(
            {"id": 6, "type": 7, "ledgerId": 99999999, "rows": [{"ledgerId": 99999998, "amount": 100}]}
        )
        self.assertIsNone(result)

    def test_process_zero_amount_returns_none(self):
        if not self.stock_account:
            self.skipTest("No Stock account configured on this company")
        _persist_ledger_mapping(880014, self.stock_account)
        # Stock account is the main ledger, row amount ~0 -> zero adjustment -> None
        result = self._processor().process(
            {"id": 7, "type": 7, "ledgerId": 880014, "rows": [{"ledgerId": 99999998, "amount": 0}]}
        )
        self.assertIsNone(result)

    # ---- warehouse / item helpers ----

    def test_get_or_create_warehouse(self):
        warehouse = self._processor()._get_or_create_warehouse()
        self.assertTrue(warehouse)
        self.assertTrue(frappe.db.exists("Warehouse", warehouse))

    def test_get_or_create_stock_item_idempotent(self):
        p = self._processor()
        item1 = p._get_or_create_stock_item("30000 - Voorraden Test - EETC")
        item2 = p._get_or_create_stock_item("30000 - Voorraden Test - EETC")
        self.assertEqual(item1, item2)
        self.assertTrue(frappe.db.exists("Item", item1))

    def test_get_or_create_stock_item_naming(self):
        item = self._processor()._get_or_create_stock_item("12345 - Inventory - EETC")
        self.assertEqual(item, "STOCK_INVENTORY")
