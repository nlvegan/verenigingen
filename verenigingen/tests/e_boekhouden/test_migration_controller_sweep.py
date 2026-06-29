"""Coverage sweep for the EBoekhoudenMigration controller orchestration.

Targets the two large self-contained pieces of
``verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py``
that no existing suite exercises:

* The INSTANCE method ``start_migration`` (~91-199): the per-phase status
  machine. Each phase method (migrate_chart_of_accounts, do_migrate_cost_centers,
  migrate_transactions_data, migrate_stock_transactions_data) catches its own
  exceptions and returns ``{"success", "message"}``; start_migration must run
  only the enabled phases, aggregate their messages, and resolve the final
  ``migration_status`` to Completed (all ok) or Failed (any phase reported
  failure). We mock ONLY those four phase methods (the live-API boundary) and
  assert the controller's OWN status transitions / result aggregation.

* ``migrate_stock_transactions_data`` (~794-826): wraps the inner
  ``migrate_stock_transactions_safe`` result into the structured phase format,
  honours its success flag, and folds skipped/processed counts into the doc.
  We mock ONLY that inner function and assert the wrapping.

What is NOT re-tested here (already covered, do not duplicate):
  parse_account_group_mappings + do_clear_existing_accounts
  (test_migration_controller_accounts_coverage / test_eboekhouden_doctype_coverage),
  start_migration_background + on_submit + import_single_mutation guards
  (test_migration_controller_guards_coverage), the phase-failure helpers
  (test_migration_phase_failure).

The eBoekhouden HTTP boundary is never driven. The api_token guard in
start_migration is satisfied by setting the tabSingles field truthy (snapshotted
and restored; the encrypted __Auth secret is never touched, so a configured
site's real credential survives).

Run with:
    cd /home/frappeuser/frappe-bench && bench --site veg11.veganisme.org \
        run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_controller_sweep
"""

from unittest.mock import patch

import frappe

from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    EBoekhoudenMigration,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

SETTINGS = "E-Boekhouden Settings"
PHASE_OK = {"success": True, "message": "ok"}


class _StartMigrationBase(EnhancedTestCase):
    """Shared setup: a configured api_token field + committed-doc cleanup.

    The instance start_migration calls frappe.db.commit() repeatedly, so its
    writes (and ours) outlive FrappeTestCase's per-test rollback. We therefore
    snapshot/restore the api_token tabSingles field and force-delete every
    migration doc we insert.
    """

    def setUp(self):
        super().setUp()
        self.company = frappe.db.get_value("Company", {}, "name")
        # Snapshot the raw tabSingles api_token value (mask/empty) so we can make
        # the guard pass and then restore it verbatim. We never touch __Auth, so
        # a configured site's real encrypted secret is left intact.
        self._orig_api_token = frappe.db.get_value(SETTINGS, SETTINGS, "api_token")
        frappe.db.set_value(SETTINGS, SETTINGS, "api_token", "TEST-TOKEN-SWEEP", update_modified=False)
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        self._created_migrations = []

    def tearDown(self):
        frappe.db.rollback()
        for name in self._created_migrations:
            if frappe.db.exists("E-Boekhouden Migration", name):
                doc = frappe.get_doc("E-Boekhouden Migration", name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("E-Boekhouden Migration", name, force=True, delete_permanently=True)
        frappe.db.set_value(
            SETTINGS, SETTINGS, "api_token", self._orig_api_token, update_modified=False
        )
        frappe.db.commit()
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        super().tearDown()

    def _make_migration(self, **kwargs):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.migration_name = kwargs.pop("migration_name", f"Sweep Migration {frappe.generate_hash()[:8]}")
        doc.migration_status = kwargs.pop("migration_status", "Draft")
        doc.company = kwargs.pop("company", self.company)
        doc.update(kwargs)
        doc.insert(ignore_permissions=True)
        self._created_migrations.append(doc.name)
        return doc


class TestStartMigrationOrchestration(_StartMigrationBase):
    """The instance start_migration per-phase status machine."""

    def test_all_phases_succeed_resolves_completed(self):
        """All four enabled phases returning success -> status Completed.

        Asserts the controller ran every phase exactly once, aggregated each
        phase message into migration_summary, drove progress to 100, and
        resolved a clean run to 'Completed' with the success operation text.
        """
        doc = self._make_migration(
            migrate_accounts=1,
            migrate_cost_centers=1,
            migrate_transactions=1,
            migrate_stock_transactions=1,
        )

        with patch.object(
            EBoekhoudenMigration, "migrate_chart_of_accounts",
            return_value={"success": True, "message": "Imported 3 accounts"},
        ) as m_coa, patch.object(
            EBoekhoudenMigration, "do_migrate_cost_centers",
            return_value={"success": True, "message": "Imported 2 cost centers"},
        ) as m_cc, patch.object(
            EBoekhoudenMigration, "migrate_transactions_data",
            return_value={"success": True, "message": "Imported 7 transactions"},
        ) as m_txn, patch.object(
            EBoekhoudenMigration, "migrate_stock_transactions_data",
            return_value={"success": True, "message": "No stock to import"},
        ) as m_stock:
            doc.start_migration()

        # Every enabled phase ran exactly once.
        self.assertEqual(m_coa.call_count, 1)
        self.assertEqual(m_cc.call_count, 1)
        self.assertEqual(m_txn.call_count, 1)
        self.assertEqual(m_stock.call_count, 1)

        doc.reload()
        self.assertEqual(doc.migration_status, "Completed")
        self.assertEqual(doc.current_operation, "Migration completed successfully")
        self.assertEqual(doc.progress_percentage, 100)
        self.assertTrue(doc.end_time)
        # Each phase message was folded into the summary.
        for fragment in (
            "Chart of Accounts: Imported 3 accounts",
            "Cost Centers: Imported 2 cost centers",
            "Transactions: Imported 7 transactions",
            "Stock Transactions: No stock to import",
        ):
            self.assertIn(fragment, doc.migration_summary)

    def test_one_failed_phase_resolves_failed_and_names_it(self):
        """A phase reporting success=False -> status Failed naming that phase.

        The other phases still ran and their messages are still recorded -- a
        failed phase does not raise, so the run completes-with-errors rather
        than aborting.
        """
        doc = self._make_migration(
            migrate_accounts=1,
            migrate_transactions=1,
        )

        with patch.object(
            EBoekhoudenMigration, "migrate_chart_of_accounts",
            return_value={"success": True, "message": "Imported 3 accounts"},
        ), patch.object(
            EBoekhoudenMigration, "migrate_transactions_data",
            return_value={"success": False, "message": "Error migrating Transactions: boom"},
        ):
            doc.start_migration()

        doc.reload()
        self.assertEqual(doc.migration_status, "Failed")
        self.assertIn("Transactions", doc.current_operation)
        self.assertIn("errors", doc.current_operation.lower())
        # Both phase messages are still recorded.
        self.assertIn("Chart of Accounts: Imported 3 accounts", doc.migration_summary)
        self.assertIn("Error migrating Transactions", doc.migration_summary)

    def test_only_enabled_phases_run(self):
        """Phases whose flag is unset are skipped entirely.

        Only migrate_accounts is enabled; the other three phase methods must
        never be invoked, and the run still resolves Completed.
        """
        doc = self._make_migration(
            migrate_accounts=1,
            migrate_cost_centers=0,
            migrate_transactions=0,
            migrate_stock_transactions=0,
        )

        with patch.object(
            EBoekhoudenMigration, "migrate_chart_of_accounts", return_value=PHASE_OK
        ) as m_coa, patch.object(
            EBoekhoudenMigration, "do_migrate_cost_centers", return_value=PHASE_OK
        ) as m_cc, patch.object(
            EBoekhoudenMigration, "migrate_transactions_data", return_value=PHASE_OK
        ) as m_txn, patch.object(
            EBoekhoudenMigration, "migrate_stock_transactions_data", return_value=PHASE_OK
        ) as m_stock:
            doc.start_migration()

        self.assertEqual(m_coa.call_count, 1)
        self.assertEqual(m_cc.call_count, 0)
        self.assertEqual(m_txn.call_count, 0)
        self.assertEqual(m_stock.call_count, 0)

        doc.reload()
        self.assertEqual(doc.migration_status, "Completed")
        self.assertIn("Chart of Accounts:", doc.migration_summary)
        self.assertNotIn("Cost Centers:", doc.migration_summary)

    def test_multiple_failed_phases_all_named(self):
        """Two phases failing -> Failed, both named in the operation message."""
        doc = self._make_migration(
            migrate_cost_centers=1,
            migrate_stock_transactions=1,
        )

        with patch.object(
            EBoekhoudenMigration, "do_migrate_cost_centers",
            return_value={"success": False, "message": "cc failed"},
        ), patch.object(
            EBoekhoudenMigration, "migrate_stock_transactions_data",
            return_value={"success": False, "message": "stock failed"},
        ):
            doc.start_migration()

        doc.reload()
        self.assertEqual(doc.migration_status, "Failed")
        self.assertIn("Cost Centers", doc.current_operation)
        self.assertIn("Stock Transactions", doc.current_operation)

    def test_missing_api_token_marks_failed_and_raises(self):
        """With no api_token the guard throws; the except block flips the doc to
        Failed, records the traceback in error_log, and re-raises.

        This exercises the instance method's own failure handler (~188-199),
        distinct from the module-level start_migration which swallows the error.
        """
        # The except block frappe.log_error()s the failure; mark it expected.
        self.expectErrorLog("E-Boekhouden Migration", "not configured")
        doc = self._make_migration(migrate_accounts=1)
        # Blank the guard field so `if not settings.api_token` fires.
        frappe.db.set_value(SETTINGS, SETTINGS, "api_token", "", update_modified=False)
        frappe.clear_document_cache(SETTINGS, SETTINGS)

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.start_migration()

        doc.reload()
        self.assertEqual(doc.migration_status, "Failed")
        self.assertIn("Migration failed", doc.current_operation)
        self.assertTrue(doc.error_log)


class TestMigrateStockTransactionsDataWrapping(EnhancedTestCase):
    """migrate_stock_transactions_data wraps migrate_stock_transactions_safe.

    No DB writes / commits happen in this method, so no special cleanup is
    needed -- a non-inserted doc carries enough state (date_from/to, counters).
    Only the inner migrate_stock_transactions_safe (the live-API boundary) is
    mocked; the wrapping logic under test is real.
    """

    INNER = "verenigingen.utils.migration.stock_migration_fixed.migrate_stock_transactions_safe"

    def _make_doc(self):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.migration_name = f"Stock Wrap {frappe.generate_hash()[:8]}"
        doc.company = frappe.db.get_value("Company", {}, "name")
        doc.total_records = 0
        doc.imported_records = 0
        return doc

    def test_success_result_is_wrapped_and_counts_folded(self):
        """A successful inner result -> success True, message passed through, and
        skipped/processed counts folded into total_records/imported_records."""
        doc = self._make_doc()
        with patch(
            self.INNER,
            return_value={
                "success": True,
                "message": "Imported 4 stock entries",
                "skipped": 2,
                "processed": 4,
            },
        ) as inner:
            result = doc.migrate_stock_transactions_data(frappe._dict())

        inner.assert_called_once()
        self.assertEqual(result, {"success": True, "message": "Imported 4 stock entries"})
        self.assertEqual(doc.total_records, 2)
        self.assertEqual(doc.imported_records, 4)

    def test_inner_failure_flag_is_honoured(self):
        """An inner result with success=False -> wrapper returns success=False
        with the inner message (not a hard-coded 'completed')."""
        doc = self._make_doc()
        with patch(
            self.INNER,
            return_value={"success": False, "message": "E-Boekhouden has no stock API"},
        ):
            result = doc.migrate_stock_transactions_data(frappe._dict())

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "E-Boekhouden has no stock API")

    def test_missing_success_key_defaults_to_false(self):
        """An inner result lacking 'success' -> wrapper coerces success to False
        (bool(result.get('success', False))) and uses the default message."""
        doc = self._make_doc()
        with patch(self.INNER, return_value={}):
            result = doc.migrate_stock_transactions_data(frappe._dict())

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Stock migration completed")

    def test_inner_exception_is_caught_and_truncated(self):
        """If the inner call raises, the wrapper logs the error and returns a
        truncated failure message (first 100 chars + '...')."""
        self.expectErrorLog("Stock Transaction Migration Error")
        doc = self._make_doc()
        long_msg = "X" * 250
        with patch(self.INNER, side_effect=RuntimeError(long_msg)):
            result = doc.migrate_stock_transactions_data(frappe._dict())

        self.assertFalse(result["success"])
        self.assertTrue(result["message"].startswith("Error migrating Stock Transactions: "))
        self.assertTrue(result["message"].endswith("..."))
        # Truncated to the first 100 chars of the exception text.
        self.assertIn("X" * 100, result["message"])
        self.assertNotIn("X" * 101, result["message"])


if __name__ == "__main__":
    import unittest

    unittest.main()
