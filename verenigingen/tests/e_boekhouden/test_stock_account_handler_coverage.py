"""
Coverage sweep for stock_account_handler.py

Target: verenigingen/e_boekhouden/utils/stock_account_handler.py

LIVENESS: LIVE. The two whitelisted endpoints
(analyze_stock_accounts_in_opening_balances / import_opening_balances_with_stock_handling)
are UI-wired @high_security_api / @critical_api entry points to the opening-balance
import. Their bodies require a live eBoekhouden HTTP fetch (EBoekhoudenAPI.make_request),
so they are OUT OF SCOPE here. The StockAccountHandler class -- which those endpoints
construct and which carries all the real logic -- is fully DB-testable.

Testable surface (REAL DB, no eBoekhouden HTTP):
- is_stock_account                    -- Account.account_type == "Stock" check
- get_stock_accounts_from_balances    -- ledger-mapping join + stock filter
- skip_stock_accounts                 -- filter/skip split
- get_stock_handling_options          -- static option dict
- get_or_create_generic_asset_account -- creates a Temporary asset account
- get_current_assets_account          -- parent resolution / fallbacks
- get_existing_temporary_account      -- equity/temporary fallback
- create_alternative_asset_mappings   -- stock->asset map
- generate_stock_account_report       -- aggregation
- create_stock_reconciliation_suggestion -- static suggestion

OUT OF SCOPE (API-REQUIRED): the two whitelisted endpoints (live eBoekhouden token).

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_stock_account_handler_coverage
"""

from unittest.mock import patch

import frappe

from verenigingen.e_boekhouden.utils.stock_account_handler import StockAccountHandler
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _StockHandlerBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Borrow the canonical EUR test company (full ERPNext Chart of Accounts).
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        cls.company = get_eur_test_company()
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    def _make_account(self, account_name, *, account_type="", root_type="Asset", is_group=0):
        """Get-or-create an Account under a matching-root group parent."""
        full = f"{account_name} - {self.abbr}"
        if frappe.db.exists("Account", full):
            return full
        parent = frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": root_type, "is_group": 1},
            "name",
        )
        doc = frappe.new_doc("Account")
        doc.account_name = account_name
        doc.company = self.company
        doc.parent_account = parent
        doc.root_type = root_type
        if account_type:
            doc.account_type = account_type
        doc.is_group = is_group
        doc.insert(ignore_permissions=True)
        return doc.name

    def _make_ledger_mapping(self, ledger_id, erpnext_account):
        """Get-or-create an E-Boekhouden Ledger Mapping row for the test."""
        existing = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}, "name")
        if existing:
            frappe.db.set_value("E-Boekhouden Ledger Mapping", existing, "erpnext_account", erpnext_account)
            return existing
        doc = frappe.new_doc("E-Boekhouden Ledger Mapping")
        doc.ledger_id = ledger_id
        doc.ledger_code = str(ledger_id)
        doc.ledger_name = f"Test Ledger {ledger_id}"
        doc.erpnext_account = erpnext_account
        doc.insert(ignore_permissions=True)
        return doc.name


class TestIsStockAccount(_StockHandlerBase):
    def setUp(self):
        super().setUp()
        self.handler = StockAccountHandler(self.company, [])

    def test_stock_account_detected(self):
        acct = self._make_account("EBKH Stock Detect", account_type="Stock")
        with self.assertNoErrorLog():
            self.assertTrue(self.handler.is_stock_account(acct))

    def test_non_stock_account_false(self):
        acct = self._make_account("EBKH NonStock Detect", account_type="")
        with self.assertNoErrorLog():
            self.assertFalse(self.handler.is_stock_account(acct))

    def test_missing_account_returns_false(self):
        with self.assertNoErrorLog():
            self.assertFalse(self.handler.is_stock_account("Definitely Not An Account - ZZZ"))


class TestGetAndSkipStockAccounts(_StockHandlerBase):
    def setUp(self):
        super().setUp()
        self.handler = StockAccountHandler(self.company, [])
        self.stock_acct = self._make_account("EBKH Stock Balances", account_type="Stock")
        self.normal_acct = self._make_account("EBKH Normal Balances", account_type="")
        self._make_ledger_mapping(990001, self.stock_acct)
        self._make_ledger_mapping(990002, self.normal_acct)

    def test_get_stock_accounts_from_balances_filters_only_stock(self):
        balances = [
            {"ledgerId": 990001, "balance": 100, "description": "stock row"},
            {"ledgerId": 990002, "balance": 50, "description": "normal row"},
            {"ledgerId": None, "balance": 7, "description": "no ledger"},
        ]
        with self.assertNoErrorLog():
            result = self.handler.get_stock_accounts_from_balances(balances)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["account"], self.stock_acct)
        self.assertEqual(result[0]["balance"], 100)

    def test_skip_stock_accounts_splits_filtered_and_skipped(self):
        balances = [
            {"ledgerId": 990001, "balance": 100, "description": "stock row"},
            {"ledgerId": 990002, "balance": 50, "description": "normal row"},
            {"ledgerId": None, "balance": 7, "description": "passthrough"},
        ]
        with self.assertNoErrorLog():
            filtered, skipped = self.handler.skip_stock_accounts(balances)
        # The stock row is removed from filtered, normal + no-ledger passthrough kept.
        skipped_accounts = {s["account"] for s in skipped}
        self.assertIn(self.stock_acct, skipped_accounts)
        self.assertEqual(len(skipped), 1)
        filtered_ledgers = {b.get("ledgerId") for b in filtered}
        self.assertIn(990002, filtered_ledgers)
        self.assertIn(None, filtered_ledgers)
        self.assertNotIn(990001, filtered_ledgers)
        # The skip reason and debug trail are populated.
        self.assertIn("Stock account", skipped[0]["reason"])
        self.assertTrue(self.handler.debug_info)

    def test_unmapped_ledger_passes_through_as_filtered(self):
        # A ledger with no mapping row is treated as a non-stock balance and kept.
        balances = [{"ledgerId": 999999, "balance": 12, "description": "unmapped"}]
        with self.assertNoErrorLog():
            filtered, skipped = self.handler.skip_stock_accounts(balances)
        self.assertEqual(skipped, [])
        self.assertEqual(len(filtered), 1)


class TestAssetAccountCreation(_StockHandlerBase):
    def setUp(self):
        super().setUp()
        self.handler = StockAccountHandler(self.company, [])

    def test_get_or_create_generic_asset_account_creates_then_idempotent(self):
        expected_name = f"Stock Value (Opening Balance) - {self.abbr}"
        with self.assertNoErrorLog():
            first = self.handler.get_or_create_generic_asset_account()
        self.assertEqual(first, expected_name)
        self.assertTrue(frappe.db.exists("Account", expected_name))
        # account_type must be a non-stock type so a JE can post to it. The
        # primary attempt always uses "Temporary"; the fallback (#788) leaves
        # account_type unset rather than the invalid "Asset" it used to set.
        acct_type = frappe.db.get_value("Account", expected_name, "account_type")
        self.assertIn(acct_type, ("Temporary", ""))
        # Second call returns the same account without creating a duplicate.
        with self.assertNoErrorLog():
            second = self.handler.get_or_create_generic_asset_account()
        self.assertEqual(second, expected_name)

    def test_get_current_assets_account_returns_a_group_asset(self):
        with self.assertNoErrorLog():
            result = self.handler.get_current_assets_account()
        self.assertTrue(result)
        self.assertIsInstance(result, str)

    def test_get_existing_temporary_account_returns_something(self):
        with self.assertNoErrorLog():
            result = self.handler.get_existing_temporary_account()
        self.assertTrue(result)
        self.assertIsInstance(result, str)

    def test_create_alternative_asset_mappings(self):
        stock_acct = self._make_account("EBKH Stock Remap", account_type="Stock")
        stock_accounts = [{"account": stock_acct, "balance": 10}]
        with self.assertNoErrorLog():
            mappings = self.handler.create_alternative_asset_mappings(stock_accounts)
        self.assertIn(stock_acct, mappings)
        # Every stock account maps to the single generic asset account.
        self.assertEqual(set(mappings.values()), {self.handler.get_or_create_generic_asset_account()})


class TestAssetAccountCreationFallback(_StockHandlerBase):
    """#788: get_or_create_generic_asset_account's fallback branch set
    account_type="Asset", which is not a valid Account.account_type option
    (valid asset-ish values include "Fixed Asset", "Current Asset", ...).  So
    whenever the primary (account_type="Temporary") attempt failed for any
    unrelated reason, the fallback's own insert() always raised ValidationError
    too, and that raise was swallowed by `except Exception as e2`, silently
    discarding the intended account and falling through to an unrelated
    equity/temporary account instead.
    """

    def setUp(self):
        super().setUp()
        self.handler = StockAccountHandler(self.company, [])
        self.expected_name = f"Stock Value (Opening Balance) - {self.abbr}"
        # Defensive: an earlier failed run may have left this behind.
        if frappe.db.exists("Account", self.expected_name):
            frappe.delete_doc("Account", self.expected_name, force=True, ignore_permissions=True)

    def test_fallback_creates_the_intended_account_when_primary_attempt_fails(self):
        """Simulate the primary (Temporary-typed) attempt failing for a reason
        unrelated to account_type -- e.g. a transient error during the
        eBoekhouden import. The fallback should then actually create the
        intended account, not silently discard it because its own account_type
        value is invalid.
        """
        from frappe.model.document import Document

        original_insert = Document.insert

        def fake_insert(self_doc, *args, **kwargs):
            if (
                self_doc.doctype == "Account"
                and self_doc.account_name == "Stock Value (Opening Balance)"
                and self_doc.account_type == "Temporary"
            ):
                raise Exception("Simulated primary-attempt failure")
            return original_insert(self_doc, *args, **kwargs)

        with patch.object(Document, "insert", fake_insert):
            result = self.handler.get_or_create_generic_asset_account()

        self.assertEqual(result, self.expected_name)
        self.assertTrue(frappe.db.exists("Account", self.expected_name))


class TestStaticHelpers(_StockHandlerBase):
    def setUp(self):
        super().setUp()
        self.handler = StockAccountHandler(self.company, [])

    def test_get_stock_handling_options_shape(self):
        opts = self.handler.get_stock_handling_options()
        self.assertEqual(
            set(opts.keys()),
            {"skip_stock_accounts", "remap_to_asset", "create_stock_reconciliation"},
        )
        self.assertTrue(opts["skip_stock_accounts"]["recommended"])
        self.assertFalse(opts["remap_to_asset"]["recommended"])

    def test_generate_stock_account_report_sums_balances(self):
        stock_accounts = [
            {"account": "A", "balance": 100.5},
            {"account": "B", "balance": 49.5},
        ]
        report = self.handler.generate_stock_account_report(stock_accounts)
        self.assertEqual(report["total_stock_accounts"], 2)
        self.assertEqual(report["total_stock_value"], 150.0)
        self.assertEqual(report["stock_accounts"], stock_accounts)
        self.assertTrue(report["recommendations"])

    def test_create_stock_reconciliation_suggestion_shape(self):
        suggestion = self.handler.create_stock_reconciliation_suggestion([{"account": "X"}])
        self.assertEqual(suggestion["method"], "Stock Reconciliation")
        self.assertEqual(suggestion["stock_accounts"], [{"account": "X"}])
        self.assertTrue(suggestion["requirements"])
        self.assertTrue(suggestion["steps"])
