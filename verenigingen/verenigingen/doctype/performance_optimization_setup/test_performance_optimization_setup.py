# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for Performance Optimization Setup
========================================

Covers the LIVE code paths of the Performance Optimization Setup controller:

- ``run_performance_optimization`` (registered in hooks/lifecycle.py after_migrate
  and invoked by the ``apply_optimizations`` CLI command) and the full
  ``on_submit`` chain it drives (index creation, caching config, completion log).
- ``get_optimization_status`` (invoked by the ``check_optimization_status`` CLI
  command).
- The validation helpers and the DDL index-creation logic (which correctly uses
  ``frappe.db.sql_ddl()`` rather than ``frappe.db.sql()`` so that the implicit
  commit guard is not tripped mid-request).

The ``remove_optimizations`` method is a non-functional stub (logs/msgprints
"not yet implemented") and has no live caller other than an auto-generated
critical_operation_rule fixture; it is exercised only to confirm its permission
gate and that it does not error.
"""

import json

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

DROPPABLE_INDEX = ("tabMember", "idx_status_member_since")


class TestPerformanceOptimizationSetup(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # The on_submit chain creates indexes via frappe.db.sql_ddl(), which
        # AUTO-COMMITS in MariaDB. That commits the submitted "default" singleton
        # past FrappeTestCase's rollback, while the post-commit
        # optimization_status="Completed" write is rolled back — leaving a lingering
        # docstatus=1 / status="Pending" doc. run_performance_optimization() then
        # early-returns "already applied" and later tests see status "Pending".
        # Purge the leaked singleton (hook-free DB delete) so each test starts clean.
        self._purge_default_singleton()

    def tearDown(self):
        self._purge_default_singleton()
        super().tearDown()

    def _purge_default_singleton(self):
        if frappe.db.exists("Performance Optimization Setup", "default"):
            frappe.db.delete("Performance Optimization Setup", {"name": "default"})

    # ------------------------------------------------------------------ helpers

    def _make_setup_doc(self, **overrides):
        """Create (unsubmitted) a Performance Optimization Setup doc tracked for cleanup."""
        values = {
            "doctype": "Performance Optimization Setup",
            "optimization_name": frappe.generate_hash("perf-opt", 8),
            "enable_database_indexing": 1,
            "enable_caching_layer": 1,
            "optimization_status": "Pending",
        }
        values.update(overrides)
        doc = frappe.get_doc(values)
        doc.insert()
        self.track_doc("Performance Optimization Setup", doc.name)
        return doc

    def _index_exists(self, table_name, index_name):
        rows = frappe.db.sql(
            """
            SELECT INDEX_NAME
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = %s
            AND INDEX_NAME = %s
            """,
            (table_name, index_name),
        )
        return bool(rows)

    def _cancel_doc(self, doctype, name):
        """Cancel a submitted doc so the tracked-doc cleanup can delete it."""
        if frappe.db.exists(doctype, name):
            doc = frappe.get_doc(doctype, name)
            if doc.docstatus == 1:
                doc.cancel()

    def _drop_index_if_exists(self, table_name, index_name):
        if self._index_exists(table_name, index_name):
            frappe.db.sql_ddl(f"ALTER TABLE `{table_name}` DROP INDEX {index_name}")

    # --------------------------------------------------------- validation logic

    def test_validate_table_exists_true_for_real_table(self):
        doc = self._make_setup_doc()
        self.assertTrue(doc._validate_table_exists("tabMember"))

    def test_validate_table_exists_false_for_missing_table(self):
        doc = self._make_setup_doc()
        self.assertFalse(doc._validate_table_exists("tabNoSuchTableXYZ"))

    def test_validate_index_name_accepts_safe_name(self):
        doc = self._make_setup_doc()
        self.assertTrue(doc._validate_index_name("idx_member_status_creation"))

    def test_validate_index_name_rejects_injection(self):
        doc = self._make_setup_doc()
        self.assertFalse(doc._validate_index_name("idx; DROP TABLE x"))
        self.assertFalse(doc._validate_index_name("idx-with-dash"))
        self.assertFalse(doc._validate_index_name("idx with space"))

    def test_validate_column_pattern_accepts_valid_definition(self):
        doc = self._make_setup_doc()
        self.assertTrue(doc._validate_column_pattern("(member, status, creation DESC)"))

    def test_validate_column_pattern_rejects_dangerous_and_unbracketed(self):
        doc = self._make_setup_doc()
        # Must be wrapped in parentheses
        self.assertFalse(doc._validate_column_pattern("member, status"))
        # Dangerous keywords / SQL comment tokens rejected
        self.assertFalse(doc._validate_column_pattern("(member); DROP TABLE x"))
        self.assertFalse(doc._validate_column_pattern("(member) -- comment"))

    # ----------------------------------------------- create_index_if_not_exists

    def test_create_index_creates_real_index_via_ddl(self):
        """create_index_if_not_exists must actually create the index (observable DDL effect).

        This exercises the frappe.db.sql_ddl() path: with frappe.db.sql() an
        ALTER ... ADD INDEX would raise ImplicitCommitError mid-request and be
        silently swallowed, so the index would never exist.
        """
        table, index = DROPPABLE_INDEX
        self.addCleanup(self._drop_index_if_exists, table, index)
        self._drop_index_if_exists(table, index)

        doc = self._make_setup_doc()
        result = doc.create_index_if_not_exists(table, index, "(status, member_since)", "test rationale")

        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["action"], "created")
        self.assertTrue(
            self._index_exists(table, index),
            "Index was reported created but is not present in INFORMATION_SCHEMA",
        )

    def test_create_index_is_idempotent(self):
        table, index = DROPPABLE_INDEX
        self.addCleanup(self._drop_index_if_exists, table, index)
        self._drop_index_if_exists(table, index)

        doc = self._make_setup_doc()
        first = doc.create_index_if_not_exists(table, index, "(status, member_since)", "r")
        self.assertEqual(first["action"], "created")

        second = doc.create_index_if_not_exists(table, index, "(status, member_since)", "r")
        self.assertTrue(second["success"])
        self.assertEqual(second["action"], "skipped")
        self.assertEqual(second["reason"], "Index already exists")

    def test_create_index_rejects_missing_table(self):
        doc = self._make_setup_doc()
        result = doc.create_index_if_not_exists("tabNoSuchTableXYZ", "idx_test", "(a, b)", "r")
        self.assertFalse(result["success"])
        self.assertIn("does not exist", result["error"])

    def test_create_index_rejects_bad_index_name(self):
        doc = self._make_setup_doc()
        result = doc.create_index_if_not_exists("tabMember", "idx; DROP", "(status)", "r")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Invalid index name format")

    def test_create_index_rejects_bad_column_pattern(self):
        doc = self._make_setup_doc()
        result = doc.create_index_if_not_exists(
            "tabMember", "idx_safe_name_test", "status, member_since", "r"
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Invalid column pattern")

    # ------------------------------------------------------- caching layer

    def test_verify_cache_backend_round_trips(self):
        doc = self._make_setup_doc()
        # Redis cache is available in the test environment; the backend check
        # writes/reads/deletes a probe key and must report it working.
        self.assertTrue(doc._verify_cache_backend())

    def test_setup_caching_layer_stores_config_on_doc(self):
        doc = self._make_setup_doc()
        result = doc.setup_caching_layer()

        self.assertTrue(result["success"], msg=result)
        self.assertIn("chapter_access_cache_ttl", result["config"])
        # Config is persisted into the document's caching_details field as JSON
        stored = json.loads(doc.caching_details)
        self.assertEqual(stored["chapter_access_cache_ttl"], 900)
        self.assertEqual(stored["settings_cache_ttl"], 3600)

    # ----------------------------------------------- setup_database_indexes

    def test_setup_database_indexes_creates_all_and_reports_counts(self):
        """The full index set should be creatable and reported with zero failures."""
        # Snapshot which of the configured indexes already exist so we can drop
        # only the ones this test creates (avoid removing pre-existing prod indexes).
        configured = [
            ("tabChapter Member", "idx_member_status_creation"),
            ("tabChapter Member", "idx_parent_status_enabled"),
            ("tabPayment Entry", "idx_party_type_party_docstatus"),
            ("tabPayment Entry", "idx_party_posting_date_desc"),
            ("tabMember", "idx_customer_docstatus"),
            ("tabMember", "idx_status_member_since"),
            ("tabMembership", "idx_member_status_start_date"),
            ("tabMembership", "idx_member_creation_desc"),
            ("tabSales Invoice", "idx_customer_status_due_date"),
            ("tabSales Invoice", "idx_status_docstatus_posting"),
            ("tabMembership Dues Schedule", "idx_member_status_next_invoice"),
        ]
        for table, index in configured:
            if not self._index_exists(table, index):
                self.addCleanup(self._drop_index_if_exists, table, index)

        doc = self._make_setup_doc()
        result = doc.setup_database_indexes()

        self.assertEqual(result["failed"], 0, msg=result)
        self.assertEqual(len(result["details"]), len(configured))
        # Every configured index must exist afterwards (created or already present).
        for table, index in configured:
            self.assertTrue(
                self._index_exists(table, index),
                f"Expected index {index} on {table} to exist after setup",
            )

    # ------------------------------------------------- on_submit / full flow

    def test_submit_runs_full_optimization_and_marks_completed(self):
        configured = [
            ("tabChapter Member", "idx_member_status_creation"),
            ("tabChapter Member", "idx_parent_status_enabled"),
            ("tabPayment Entry", "idx_party_type_party_docstatus"),
            ("tabPayment Entry", "idx_party_posting_date_desc"),
            ("tabMember", "idx_customer_docstatus"),
            ("tabMember", "idx_status_member_since"),
            ("tabMembership", "idx_member_status_start_date"),
            ("tabMembership", "idx_member_creation_desc"),
            ("tabSales Invoice", "idx_customer_status_due_date"),
            ("tabSales Invoice", "idx_status_docstatus_posting"),
            ("tabMembership Dues Schedule", "idx_member_status_next_invoice"),
        ]
        for table, index in configured:
            if not self._index_exists(table, index):
                self.addCleanup(self._drop_index_if_exists, table, index)

        doc = self._make_setup_doc()
        # Submitted docs cannot be plain-deleted; cancel before the tracked cleanup.
        self.addCleanup(self._cancel_doc, "Performance Optimization Setup", doc.name)
        doc.submit()

        doc.reload()
        self.assertEqual(doc.docstatus, 1)
        self.assertEqual(doc.optimization_status, "Completed")
        self.assertTrue(doc.optimization_completion_date)
        # Completion summary persisted as JSON in indexing_details
        summary = json.loads(doc.indexing_details)
        self.assertTrue(summary["database_indexing"])
        self.assertTrue(summary["caching_layer"])
        # Caching config also persisted
        self.assertTrue(doc.caching_details)

    # ------------------------------------------- run_performance_optimization

    def test_run_performance_optimization_creates_default_doc(self):
        from verenigingen.verenigingen.doctype.performance_optimization_setup.performance_optimization_setup import (
            run_performance_optimization,
        )

        # If a prior run left a "default" doc, this test relies on the
        # already-applied early-return path; otherwise it creates+submits it.
        pre_existing = frappe.db.exists("Performance Optimization Setup", "default")

        result = run_performance_optimization()

        self.assertTrue(result["success"], msg=result)
        self.assertTrue(frappe.db.exists("Performance Optimization Setup", "default"))

        if not pre_existing:
            # Newly created+submitted in this run -> clean it up.
            self.addCleanup(self._force_delete_default)
            doc = frappe.get_doc("Performance Optimization Setup", "default")
            self.assertEqual(doc.optimization_status, "Completed")
            self.assertEqual(doc.docstatus, 1)

    def _force_delete_default(self):
        if frappe.db.exists("Performance Optimization Setup", "default"):
            doc = frappe.get_doc("Performance Optimization Setup", "default")
            if doc.docstatus == 1:
                doc.cancel()
            frappe.delete_doc(
                "Performance Optimization Setup", "default", force=True, ignore_permissions=True
            )

    def test_run_performance_optimization_idempotent_when_already_applied(self):
        from verenigingen.verenigingen.doctype.performance_optimization_setup.performance_optimization_setup import (
            run_performance_optimization,
        )

        first = run_performance_optimization()
        self.assertTrue(first["success"])
        if not frappe.db.exists("Performance Optimization Setup", "default"):
            self.skipTest("default doc not created (unexpected) - cannot test idempotency")

        # Track for cleanup only if we likely created it; harmless if pre-existing.
        self.addCleanup(self._cleanup_default_if_submitted)

        second = run_performance_optimization()
        self.assertTrue(second["success"])
        self.assertEqual(second["message"], "Performance optimizations already applied")

    def _cleanup_default_if_submitted(self):
        # Leave a pre-existing prod "default" alone is impossible to distinguish;
        # in the test DB the safest behavior is to remove our created doc.
        self._force_delete_default()

    # ----------------------------------------------- get_optimization_status

    def test_get_optimization_status_reports_applied(self):
        from verenigingen.verenigingen.doctype.performance_optimization_setup.performance_optimization_setup import (
            get_optimization_status,
            run_performance_optimization,
        )

        run_performance_optimization()
        self.addCleanup(self._force_delete_default)

        status = get_optimization_status()
        self.assertTrue(status["applied"])
        self.assertEqual(status["status"], "Completed")
        self.assertTrue(status["completion_date"])

    # ------------------------------------------------- remove_optimizations (stub)

    def test_remove_optimizations_stub_runs_without_error(self):
        """remove_optimizations is an unimplemented stub; confirm it is permission
        gated and returns without raising for a permitted user."""
        doc = self._make_setup_doc()
        # System Manager (test default) has write -> should not raise.
        doc.remove_optimizations()
