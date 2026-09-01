"""Tests for _finalize_mutation_savepoint (audit T2.3; non-resumable handling #572).

The e-Boekhouden batch import wraps each mutation in a DB savepoint so a
failure partway through a mutation rolls back its partial writes instead of
leaving an orphaned half-record. _finalize_mutation_savepoint performs that
rollback-or-release.

Since #572 it routes both halves through the shared helpers in
``utils.transaction_errors`` (rollback_to_savepoint / release_savepoint_if_present)
instead of a hand-written try/except that swallowed EVERYTHING, including a 1213
deadlock raised by the ``ROLLBACK TO SAVEPOINT`` itself. A missing savepoint (1305)
is still tolerated; anything else -- in particular the two errors in
``transaction_errors.NON_RESUMABLE_DB_ERRORS`` -- now propagates, so the batch loop
that calls this from a ``finally`` stops feeding mutations into a transaction the
server has already discarded instead of continuing as if nothing happened.

Run with:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_mutation_savepoint
"""

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _finalize_mutation_savepoint,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.non_resumable_errors import deadlock


class TestFinalizeMutationSavepoint(EnhancedTestCase):
    """A per-mutation savepoint rolls back partial writes on failure."""

    def _savepoint_with_todo(self):
        """Open a savepoint and insert a ToDo inside it; return (name, todo_name)."""
        savepoint_name = f"eb_test_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(savepoint_name)
        todo = frappe.get_doc(
            {"doctype": "ToDo", "description": f"savepoint test {frappe.generate_hash(length=8)}"}
        )
        todo.insert(ignore_permissions=True)
        return savepoint_name, todo.name

    def test_rollback_undoes_writes_when_not_succeeded(self):
        """succeeded=False rolls the savepoint back — the mutation's writes vanish."""
        savepoint_name, todo_name = self._savepoint_with_todo()
        self.assertTrue(frappe.db.exists("ToDo", todo_name))

        _finalize_mutation_savepoint(savepoint_name, succeeded=False)

        self.assertFalse(
            frappe.db.exists("ToDo", todo_name),
            "A non-succeeded mutation's partial writes must be rolled back",
        )

    def test_release_keeps_writes_when_succeeded(self):
        """succeeded=True releases the savepoint — the mutation's writes persist."""
        savepoint_name, todo_name = self._savepoint_with_todo()

        _finalize_mutation_savepoint(savepoint_name, succeeded=True)

        self.assertTrue(
            frappe.db.exists("ToDo", todo_name),
            "A succeeded mutation's writes must be kept",
        )
        frappe.delete_doc("ToDo", todo_name, ignore_permissions=True, force=True)

    def test_missing_savepoint_does_not_raise(self):
        """A dropped/missing savepoint (1305) is tolerated — it must not abort the batch."""
        # rollback_to_savepoint() itself reports the tolerated 1305 to Error Log
        # (its own documented, tested behaviour) -- expected here, not a leak.
        self.expectErrorLog("Savepoint rollback skipped")
        _finalize_mutation_savepoint(
            f"eb_test_missing_{frappe.generate_hash(length=8)}", succeeded=False
        )
        # No exception is the assertion: the shared helper already has its own
        # coverage (test_savepoint_rollback_cannot_mask_the_error.py) proving the
        # 1305 case reports to Error Log rather than debug_info, which this
        # function no longer collects at all -- see the propagation test below
        # for what DOES still need to reach the caller.

    def test_non_resumable_error_from_rollback_propagates(self):
        """A 1213 raised by the ROLLBACK TO SAVEPOINT itself must NOT be swallowed (#572).

        Before #572 this landed in `debug_info` as one WARNING line and the batch
        carried on feeding mutations into a transaction the server had already
        discarded. Patches the real driver call the way
        test_savepoint_rollback_cannot_mask_the_error.py does, rather than a stand-in
        double, so this proves the CLASS of error propagates, not just that some
        exception does.
        """
        savepoint_name = f"eb_test_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(savepoint_name)

        def _deadlocking_rollback(*, save_point=None, chain=False):
            raise deadlock()

        frappe.local.db.rollback = _deadlocking_rollback
        self.addCleanup(frappe.local.db.__dict__.pop, "rollback", None)

        with self.assertRaises(frappe.QueryDeadlockError):
            _finalize_mutation_savepoint(savepoint_name, succeeded=False)
