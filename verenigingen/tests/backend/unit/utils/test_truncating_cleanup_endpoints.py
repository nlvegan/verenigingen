"""Regression tests for the admin_tools cleanup endpoints that TRUNCATE.

These three endpoints sit behind buttons on the admin_tools page and share one
failure mode with the (now fixed) API Audit Log "Clear All Logs" button:

    frappe.db.sql("TRUNCATE ...") is DDL, and Frappe refuses any statement in
    IMPLICIT_COMMIT_QUERY_TYPES ({start, alter, drop, create, begin, truncate})
    once transaction_writes > 0 -- raising ImplicitCommitError.

``clear_all_deleted_documents`` was broken for every input: it calls
``get_deleted_document_statistics()``, which is ``@high_security_api`` and so
writes an API Audit Log row when it returns, and the very next statement is a raw
TRUNCATE. Measured: transaction_writes 0 -> 1 -> TRUNCATE raises. The other two
happened to be reachable with a clean transaction but carried the same landmine.

NOT PARALLEL-SAFE: these endpoints truncate `tabVersion` and
`tabDeleted Document` wholesale -- that is the behaviour under test, not an
accident. Do not run this module concurrently with tests that assert on version
history or on soft-deleted documents.
"""

import unittest

import frappe


class TruncatingCleanupEndpointTest(unittest.TestCase):
    """Shared guard: these are Administrator-only destructive endpoints."""

    def setUp(self):
        super().setUp()
        if frappe.session.user != "Administrator":
            self.skipTest("destructive cleanup endpoints require Administrator")

    def _seed_pending_write(self):
        """Leave one uncommitted write in the transaction, then assert it landed.

        This is the precondition that armed the bug. Registered for cleanup
        BEFORE the write so a failing assertion below cannot leak it into the
        shared site.
        """
        todo = frappe.new_doc("ToDo")
        todo.description = "truncating-cleanup regression probe"
        todo.insert()
        self.addCleanup(self._discard_probe, todo.name)
        self.assertGreater(frappe.db.transaction_writes, 0, "expected a pending write")

    @staticmethod
    def _discard_probe(name):
        if frappe.db.exists("ToDo", name):
            # Security: test-local teardown of a ToDo this test created moments
            # ago, by name. ignore_permissions because the probe must be removed
            # even when the assertion under test failed; no user input reaches it.
            frappe.delete_doc("ToDo", name, force=True, ignore_permissions=True)
            frappe.db.commit()


class TestClearAllDeletedDocuments(TruncatingCleanupEndpointTest):
    def test_clears_the_table_and_reports_success(self):
        """Regression: returned {"success": False, ...} for every input because
        the @high_security_api statistics helper called immediately above leaves
        an uncommitted audit row, so the raw TRUNCATE tripped the guard."""
        from verenigingen.utils.deleted_document_cleanup import clear_all_deleted_documents

        result = clear_all_deleted_documents()

        self.assertTrue(result.get("success"), f"clear failed: {result.get('message')}")
        self.assertEqual(frappe.db.count("Deleted Document"), 0)

    def test_survives_a_caller_that_already_wrote(self):
        """The endpoint must not depend on being the first thing in a request."""
        from verenigingen.utils.deleted_document_cleanup import clear_all_deleted_documents

        self._seed_pending_write()

        result = clear_all_deleted_documents()

        self.assertTrue(result.get("success"), f"clear failed: {result.get('message')}")


class TestClearAllVersions(TruncatingCleanupEndpointTest):
    def test_survives_a_caller_that_already_wrote(self):
        """clear_all_versions only reads before its TRUNCATE, so it happened to
        work -- but one upstream write armed it. Pin the hardened behaviour."""
        from verenigingen.utils.version_cleanup import clear_all_versions

        self._seed_pending_write()

        result = clear_all_versions()

        self.assertTrue(result.get("success"), f"clear failed: {result.get('message')}")
        self.assertEqual(frappe.db.count("Version"), 0)


class TestNuclearTruncate(TruncatingCleanupEndpointTest):
    def test_dry_run_truncates_nothing(self):
        from verenigingen.utils.version_cleanup import nuclear_truncate_version_and_deleted_tables

        result = nuclear_truncate_version_and_deleted_tables(confirm_nuclear_truncate=True, dry_run=True)

        self.assertEqual(result.get("tables_truncated"), [])

    def test_survives_a_caller_that_already_wrote(self):
        """This one carried both landmines: frappe.db.begin() followed by two
        raw TRUNCATEs."""
        from verenigingen.utils.version_cleanup import nuclear_truncate_version_and_deleted_tables

        self._seed_pending_write()

        result = nuclear_truncate_version_and_deleted_tables(confirm_nuclear_truncate=True, dry_run=False)

        # This endpoint reports outcome through tables_truncated/errors, not a
        # success flag.
        self.assertEqual(result.get("errors"), [], f"truncate errored: {result.get('summary')}")
        self.assertEqual(
            sorted(result.get("tables_truncated", [])),
            ["tabDeleted Document", "tabVersion"],
        )
        self.assertEqual(frappe.db.count("Version"), 0)
        self.assertEqual(frappe.db.count("Deleted Document"), 0)


if __name__ == "__main__":
    unittest.main()
