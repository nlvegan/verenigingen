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
    """Return a non-group Stock account for the company, creating one if absent.

    A Stock account must hang under an Asset group; we reuse the company's first
    Asset group as parent. This makes the stock-path tests deterministic instead
    of silently skipping on sites without a pre-seeded Stock account.
    """
    existing = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Stock", "is_group": 0}, "name"
    )
    if existing:
        return existing

    abbr = frappe.db.get_value("Company", company, "abbr")
    full = f"EBkh Test Stock - {abbr}"
    if frappe.db.exists("Account", full):
        return full

    parent = frappe.db.get_value("Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name")
    if not parent:
        return None

    doc = frappe.new_doc("Account")
    doc.account_name = "EBkh Test Stock"
    doc.company = company
    doc.parent_account = parent
    doc.root_type = "Asset"
    doc.account_type = "Stock"
    doc.is_group = 0
    doc.insert(ignore_permissions=True)
    return doc.name


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
        # Deterministic: the helper creates a Stock account if none exists, so the
        # stock-path tests below must not silently skip.
        assert cls.stock_account, f"Could not get/create a Stock account for {cls.company}"

    def _processor(self):
        return StockProcessor(self.company)

    # ---- _is_stock_account ----

    def test_is_stock_account_none(self):
        self.assertFalse(self._processor()._is_stock_account(None))

    def test_is_stock_account_nonexistent(self):
        self.assertFalse(self._processor()._is_stock_account("No Such Account - X"))

    def test_is_stock_account_true_for_stock(self):
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
        _persist_ledger_mapping(880012, self.stock_account)
        self.assertTrue(self._processor().can_process({"id": 3, "type": 7, "ledgerId": 880012, "rows": []}))

    def test_type10_with_stock_row_ledger_true(self):
        _persist_ledger_mapping(880013, self.stock_account)
        self.assertTrue(
            self._processor().can_process(
                {"id": 4, "type": 10, "ledgerId": 99999999, "rows": [{"ledgerId": 880013}]}
            )
        )

    # ---- process() early returns ----

    def test_process_no_rows_returns_none(self):
        # None is returned on many paths; pin the SPECIFIC "no rows" branch via debug_info.
        p = self._processor()
        result = p.process({"id": 5, "type": 7, "rows": []})
        self.assertIsNone(result)
        self.assertTrue(any("has no rows" in m for m in p.debug_info), p.debug_info)

    def test_process_no_stock_account_returns_none(self):
        # Rows present but none map to a stock account -> "No stock account" branch.
        p = self._processor()
        result = p.process(
            {"id": 6, "type": 7, "ledgerId": 99999999, "rows": [{"ledgerId": 99999998, "amount": 100}]}
        )
        self.assertIsNone(result)
        self.assertTrue(any("No stock account" in m for m in p.debug_info), p.debug_info)

    def test_process_zero_amount_returns_none(self):
        # Stock account is the main ledger, row amount ~0 -> zero adjustment -> None.
        # Pin the SPECIFIC "zero amount" branch (distinct from no-rows / no-account).
        _persist_ledger_mapping(880014, self.stock_account)
        p = self._processor()
        result = p.process(
            {"id": 7, "type": 7, "ledgerId": 880014, "rows": [{"ledgerId": 99999998, "amount": 0}]}
        )
        self.assertIsNone(result)
        self.assertTrue(any("zero amount" in m for m in p.debug_info), p.debug_info)

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
        # The helper's contract is to create a *stock* item (stock_processor.py
        # ~L297-298: is_stock_item = 1).
        self.assertEqual(frappe.db.get_value("Item", item1, "is_stock_item"), 1)

    def test_get_or_create_stock_item_naming(self):
        item = self._processor()._get_or_create_stock_item("12345 - Inventory - EETC")
        self.assertEqual(item, "STOCK_INVENTORY")


def _setup_expense_account(company):
    """Return a non-group Expense account to act as the stock counterparty."""
    return frappe.db.get_value("Account", {"company": company, "is_group": 0, "root_type": "Expense"}, "name")


def _ensure_current_fiscal_year():
    """Ensure a Fiscal Year covers today's date AND applies to every company.

    erpnext's global test setup restricts the current calendar-year Fiscal Year
    to ``_Test Company`` via the FY ``companies`` child table, so submitting a
    dated Stock Reconciliation against the EUR test company otherwise fails
    "Date <today> is not in any active Fiscal Year". We provision the FY via the
    product creator and drop every company restriction on the FYs covering
    today(), commit (to survive per-test rollback), and bust the per-company FY
    cache.
    """
    from frappe.utils import getdate, today

    from verenigingen.tests.setup import ensure_test_fiscal_year_for_all_companies

    ensure_test_fiscal_year_for_all_companies()

    d = getdate(today())
    covering = frappe.db.sql(
        """
        SELECT name FROM `tabFiscal Year`
        WHERE %s BETWEEN year_start_date AND year_end_date AND disabled = 0
        """,
        (d,),
        pluck=True,
    )
    for fy_name in covering:
        if frappe.db.exists("Fiscal Year Company", {"parent": fy_name}):
            frappe.db.delete("Fiscal Year Company", {"parent": fy_name})
    frappe.db.commit()  # fixture must outlive per-test rollback
    frappe.cache().delete_value("fiscal_years")


class TestStockReconciliationCreateIntegration(EnhancedTestCase):
    """Integration tests that drive the REAL Stock Reconciliation create path
    (StockProcessor.process -> _create_stock_reconciliation) and assert the
    submitted document's stock content: item, warehouse, qty, valuation_rate,
    amount, purpose, expense_account, and docstatus.

    This exercises the full submit chain (Stock Reconciliation insert + submit,
    which posts stock ledger + GL entries) with real fixtures: a Stock account,
    an Expense counterparty account, and E-Boekhouden Ledger Mappings linking
    both. There is no external boundary here -- StockProcessor.process is fully
    DB-driven.

    NOTE: Stock Reconciliation on this site has no ``eboekhouden_mutation_nr``
    custom field, so the processor's attempt to stash the mutation id is a
    silent in-memory no-op (the value is dropped on save). This does not affect
    the financial content asserted below. The idempotency/duplicate-handling
    branch that relies on that field is therefore NOT covered here and is
    flagged in the agent report.
    """

    STOCK_LEDGER_ID = 882001
    EXPENSE_LEDGER_ID = 882002

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()
        _ensure_current_fiscal_year()
        cls.stock_account = _setup_stock_account(cls.company)
        assert cls.stock_account, f"Could not get/create a Stock account for {cls.company}"
        cls.expense_account = _setup_expense_account(cls.company)
        assert cls.expense_account, f"No Expense account for {cls.company}"
        _persist_ledger_mapping(cls.STOCK_LEDGER_ID, cls.stock_account)
        _persist_ledger_mapping(cls.EXPENSE_LEDGER_ID, cls.expense_account)

    def _processor(self):
        return StockProcessor(self.company)

    _id_counter = 0

    def _unique_id(self):
        import random

        TestStockReconciliationCreateIntegration._id_counter += 1
        return (
            (int(frappe.utils.now_datetime().timestamp()) % 2000000) * 1000
            + random.randint(0, 999)
            + TestStockReconciliationCreateIntegration._id_counter
        )

    def test_stock_reconciliation_created_and_submitted_with_content(self):
        p = self._processor()
        mut = {
            "id": self._unique_id(),
            "type": 7,
            "date": frappe.utils.today(),
            "description": "integration stock adjustment",
            # Stock account is the MAIN ledger -> processor takes amount = -row_amount.
            "ledgerId": self.STOCK_LEDGER_ID,
            "rows": [{"ledgerId": self.EXPENSE_LEDGER_ID, "amount": 25.0}],
        }
        self.assertTrue(p.can_process(mut))

        doc = p.process(mut)
        self.assertIsNotNone(doc, p.debug_info)

        saved = frappe.get_doc("Stock Reconciliation", doc.name)
        # The Stock Reconciliation must be submitted (posts stock + GL entries).
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(saved.purpose, "Stock Reconciliation")
        self.assertEqual(saved.company, self.company)
        self.assertEqual(saved.expense_account, self.stock_account)

        # Exactly one stock line, with the expected item/warehouse/qty/valuation.
        self.assertEqual(len(saved.items), 1)
        line = saved.items[0]
        # Item is the get-or-create stock item for the stock account, and it is
        # a real stock item that exists in the DB.
        self.assertTrue(line.item_code)
        self.assertTrue(frappe.db.exists("Item", line.item_code))
        self.assertEqual(frappe.db.get_value("Item", line.item_code, "is_stock_item"), 1)
        # Warehouse is a real non-group warehouse for the company.
        self.assertTrue(line.warehouse)
        self.assertEqual(frappe.db.get_value("Warehouse", line.warehouse, "company"), self.company)
        # qty == abs(amount); rate is the product's flat €1.00/unit assumption;
        # amount == abs(amount). amount here is -row_amount = -25.0 -> abs 25.0.
        self.assertEqual(line.qty, 25.0)
        self.assertEqual(line.valuation_rate, 1.0)
        self.assertEqual(line.amount, 25.0)

        # The submit must have produced a real stock effect: a Stock Ledger
        # Entry for this item/warehouse tied to the reconciliation.
        sle_count = frappe.db.count(
            "Stock Ledger Entry",
            {"voucher_type": "Stock Reconciliation", "voucher_no": saved.name},
        )
        self.assertGreaterEqual(sle_count, 1)

    def test_stock_reconciliation_amount_from_stock_row_ledger(self):
        # When the stock account is a ROW ledger (not the main ledger), the
        # processor takes amount = +row_amount. Assert qty/amount track that.
        p = self._processor()
        # main ledger maps to the expense (non-stock) account; stock is in the row.
        mut = {
            "id": self._unique_id(),
            "type": 10,
            "date": frappe.utils.today(),
            "description": "integration stock row adjustment",
            "ledgerId": self.EXPENSE_LEDGER_ID,
            "rows": [{"ledgerId": self.STOCK_LEDGER_ID, "amount": 12.0}],
        }
        self.assertTrue(p.can_process(mut))
        doc = p.process(mut)
        self.assertIsNotNone(doc, p.debug_info)

        saved = frappe.get_doc("Stock Reconciliation", doc.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(saved.expense_account, self.stock_account)
        self.assertEqual(len(saved.items), 1)
        self.assertEqual(saved.items[0].qty, 12.0)
        self.assertEqual(saved.items[0].amount, 12.0)
        self.assertEqual(saved.items[0].valuation_rate, 1.0)
