"""
Tests for verenigingen/e_boekhouden/utils/cleanup_utils.py

These exercise the cleanup functions along SAFE, deterministic paths that do not
require a live eBoekhouden connection and do not destroy shared fixture data:

  - cleanup_chart_of_accounts: safe-mode (skips GL-linked / system / group accts),
    and successfully deleting a fresh leaf account flagged as eBoekhouden-imported.
  - cleanup_orphaned_gl_entries: returns a well-formed result (no orphans present).
  - cleanup_cancelled_payment_gl_entries: returns success.
  - _cleanup_orphaned_bank_transactions: returns a well-formed result.
  - get_cleanup_dependencies: returns the expected count dict.
  - cleanup_payment_entries / cleanup_sales_invoices / cleanup_purchase_invoices:
    helper functions on empty + missing-name input.

Tests run as Administrator (EnhancedTestCase), which holds Account delete perms.

Run with:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_cleanup_utils
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.cleanup_utils import (
    _cleanup_orphaned_bank_transactions,
    cleanup_cancelled_payment_gl_entries,
    cleanup_chart_of_accounts,
    cleanup_orphaned_gl_entries,
    cleanup_payment_entries,
    cleanup_purchase_invoices,
    cleanup_sales_invoices,
    get_cleanup_dependencies,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _CleanupTestBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST EBkh Cleanup Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TECL"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def _persist_eboekhouden_account(self, acct_name, grootboek="99999"):
        """Create a fresh leaf account flagged as imported from eBoekhouden."""
        parent = frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": "Expense", "is_group": 1},
            "name",
        )
        full = f"{acct_name} - {self.abbr}"
        if frappe.db.exists("Account", full):
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = self.company
        doc.parent_account = parent
        doc.root_type = "Expense"
        doc.is_group = 0
        if doc.meta.has_field("eboekhouden_grootboek_nummer"):
            doc.eboekhouden_grootboek_nummer = grootboek
        doc.insert(ignore_permissions=True)
        return doc.name


class TestCleanupChartOfAccounts(_CleanupTestBase):
    def test_string_boolean_args_parsed(self):
        # delete_all_accounts="false" / force_delete="0" must be parsed, not crash.
        result = cleanup_chart_of_accounts(self.company, delete_all_accounts="false", force_delete="0")
        self.assertTrue(result["success"])
        self.assertIn("results", result)

    def test_deletes_fresh_eboekhouden_leaf_account(self):
        if not frappe.get_meta("Account").has_field("eboekhouden_grootboek_nummer"):
            self.skipTest("eboekhouden_grootboek_nummer custom field not installed")
        acct = self._persist_eboekhouden_account("EBkh Cleanup Leaf")
        self.assertTrue(frappe.db.exists("Account", acct))

        # Safe mode, only eBoekhouden accounts. Fresh leaf has no GL entries,
        # is not a system account, and has no children -> should be deleted.
        result = cleanup_chart_of_accounts(self.company, delete_all_accounts=0, force_delete=0)
        self.assertTrue(result["success"])
        self.assertFalse(frappe.db.exists("Account", acct))
        self.assertGreaterEqual(result["results"]["accounts_deleted"], 1)

    def test_no_eboekhouden_accounts_is_noop(self):
        # After the prior test there should be no flagged accounts left for this
        # company; running again should succeed with zero deletions.
        result = cleanup_chart_of_accounts(self.company, delete_all_accounts=0, force_delete=0)
        self.assertTrue(result["success"])
        self.assertEqual(result["results"]["accounts_deleted"], 0)


class TestCleanupOrphanedGLEntries(_CleanupTestBase):
    def test_returns_wellformed_result(self):
        result = cleanup_orphaned_gl_entries()
        self.assertTrue(result["success"])
        # Backward-compat aggregate key present
        self.assertIn("deleted_entries", result)
        self.assertIn("deleted_gl_entries", result)
        self.assertIsInstance(result["deleted_gl_entries"], int)


class TestCleanupCancelledPaymentGLEntries(_CleanupTestBase):
    def test_returns_success(self):
        result = cleanup_cancelled_payment_gl_entries()
        self.assertTrue(result["success"])
        self.assertIn("message", result)


class TestCleanupOrphanedBankTransactions(_CleanupTestBase):
    def test_returns_wellformed_result(self):
        result = _cleanup_orphaned_bank_transactions()
        self.assertIn("deleted", result)
        self.assertIn("errors", result)
        self.assertIsInstance(result["deleted"], int)


class TestGetCleanupDependencies(_CleanupTestBase):
    def test_returns_count_dict(self):
        deps = get_cleanup_dependencies(self.company)
        expected_keys = {"gl_entries", "invoices", "purchases", "payments", "journals"}
        self.assertEqual(set(deps.keys()), expected_keys)
        for v in deps.values():
            self.assertIsInstance(v, int)
            self.assertGreaterEqual(v, 0)


class TestCleanupListHelpers(_CleanupTestBase):
    def test_cleanup_payment_entries_empty(self):
        result = cleanup_payment_entries([], "test")
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["errors"], [])

    def test_cleanup_sales_invoices_empty(self):
        result = cleanup_sales_invoices([], "test")
        self.assertEqual(result["deleted"], 0)

    def test_cleanup_purchase_invoices_empty(self):
        result = cleanup_purchase_invoices([], "test")
        self.assertEqual(result["deleted"], 0)

    def test_cleanup_payment_entries_missing_name_collects_error(self):
        # A non-existent PE name -> get_doc raises -> error captured, no crash.
        result = cleanup_payment_entries(["NO-SUCH-PE-XYZ"], "test")
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(result["errors"]), 1)

    def test_cleanup_sales_invoices_missing_name_collects_error(self):
        result = cleanup_sales_invoices(["NO-SUCH-SI-XYZ"], "test")
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(result["errors"]), 1)

    def test_cleanup_purchase_invoices_missing_name_collects_error(self):
        result = cleanup_purchase_invoices(["NO-SUCH-PI-XYZ"], "test")
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(result["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
