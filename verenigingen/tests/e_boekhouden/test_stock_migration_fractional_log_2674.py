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


class TestMigrationRunReporting(EnhancedTestCase):
    """Sibling defects in the same file: failed run reported as success, and
    missing-f summary strings."""

    API = "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI"

    def test_standalone_reports_failure_when_the_run_fails(self):
        from verenigingen.utils.migration.stock_migration import migrate_stock_transactions_standalone

        settings = frappe._dict(api_token="x")
        with (
            patch(f"{MOD}.frappe.get_single", return_value=settings),
            patch(self.API, side_effect=RuntimeError("api down")),
            patch("frappe.log_error"),
        ):
            result = migrate_stock_transactions_standalone(
                f"no-such-migration-{frappe.generate_hash()[:8]}", "2026-01-01", "2026-01-31"
            )
        self.assertFalse(result["success"], result)
        self.assertIn("api down", result["error"])

    def test_returned_summary_interpolates_counts(self):
        migrator = StockTransactionMigrator(frappe._dict(dry_run=False))
        migrator.stock_transactions_created = 3
        migrator.stock_transactions_failed = 2
        migrator.stock_transactions_skipped = 1
        api = patch(self.API)
        accounts = [{"account_number": "1300", "account_name": "Voorraad"}]
        with api as api_cls, patch.object(migrator, "get_stock_accounts", return_value=accounts):
            api_cls.return_value.get_mutations.return_value = {"success": True, "data": '{"items": []}'}
            summary = migrator.migrate_stock_transactions(frappe._dict(), "2026-01-01", "2026-01-31")
        self.assertEqual(summary, "Created 3 stock entries | Failed: 2 | Skipped: 1")

    def test_dry_run_summary_interpolates_count(self):
        migrator = StockTransactionMigrator(frappe._dict(dry_run=True))
        accounts = [{"account_number": "1300", "account_name": "Voorraad"}]
        with patch(self.API) as api_cls, patch.object(migrator, "get_stock_accounts", return_value=accounts):
            api_cls.return_value.get_mutations.return_value = {"success": True, "data": '{"items": []}'}
            summary = migrator.migrate_stock_transactions(frappe._dict(), "2026-01-01", "2026-01-31")
        self.assertEqual(summary, "Dry Run: Found 0 stock transactions to migrate")
