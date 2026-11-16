"""#2674: the fractional-quantity log of StockTransactionMigrator.create_stock_entry.

Drives the real ``create_stock_entry`` down its "cannot be a fraction" branch and
asserts on the channel the message really goes to: ``frappe.log_error`` (reached
through ``safe_log_error``). Only the DB-heavy collaborators are stubbed (company
settings, warehouse, item) and ``StockEntry.insert`` (the ERPNext validation
boundary; the doc itself is built for real) raises ERPNext's fraction error text.
The logging path under test is real. The error text is injected, not produced by
ERPNext, so this does not prove ERPNext still words it "cannot be a fraction".

Two defects are pinned: the continuation literal ``"Account: {account_code} ..."``
had no ``f`` prefix (braces logged literally), and the handler imported the
non-existent ``verenigingen.utils.error_log_fix``, so the message was never logged
at all (ModuleNotFoundError escaped create_stock_entry).
"""

from unittest.mock import patch

import frappe

from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.migration.stock_migration import StockTransactionMigrator

MOD = "verenigingen.utils.migration.stock_migration"


class TestFractionalQuantityLog(EnhancedTestCase):
    def _drive_create_stock_entry(self, error_text):
        migrator = StockTransactionMigrator(frappe._dict())
        settings = frappe._dict(default_company="Stub Co", default_cost_center="Stub CC")
        calls = []

        def record(*args, **kwargs):
            calls.append(kwargs)

        with (
            patch(f"{MOD}.frappe.get_single", return_value=settings),
            patch.object(StockEntry, "insert", side_effect=frappe.ValidationError(error_text)),
            patch.object(migrator, "get_or_create_migration_warehouse", return_value="WH"),
            patch.object(migrator, "get_or_create_migration_item", return_value="MIGR-ITEM"),
            patch("frappe.log_error", side_effect=record),
        ):
            result = migrator.create_stock_entry(
                "2026-01-01", "Material Receipt", "12345", "Voorraad Test", 0.5, 12.5, "L1", {}
            )
        return result, calls

    def test_fractional_branch_logs_the_real_account_values(self):
        result, calls = self._drive_create_stock_entry("Quantity (Nos) cannot be a fraction in row 1")
        self.assertIsNone(result)
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0]["title"], "Stock Entry: Fractional Quantity")
        message = calls[0]["message"]
        self.assertIn("Account: 12345 - Voorraad Test", message)
        self.assertIn("got 0.5", message)
        self.assertNotIn("{account_code}", message)
        self.assertNotIn("{account_name}", message)

    def test_other_errors_still_take_the_generic_branch(self):
        """Control: a non-fraction error must not use the fractional message."""
        result, calls = self._drive_create_stock_entry("Something else broke")
        self.assertIsNone(result)
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0]["title"], "Stock Entry Creation Failed")
        self.assertIn("Something else broke", calls[0]["message"])
