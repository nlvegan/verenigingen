"""Tests for _finalize_mutation_savepoint (audit T2.3).

The e-Boekhouden batch import wraps each mutation in a DB savepoint so a
failure partway through a mutation rolls back its partial writes instead of
leaving an orphaned half-record. _finalize_mutation_savepoint performs that
rollback-or-release.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_mutation_savepoint
"""

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _finalize_mutation_savepoint,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


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

        _finalize_mutation_savepoint(savepoint_name, succeeded=False, debug_info=[])

        self.assertFalse(
            frappe.db.exists("ToDo", todo_name),
            "A non-succeeded mutation's partial writes must be rolled back",
        )

    def test_release_keeps_writes_when_succeeded(self):
        """succeeded=True releases the savepoint — the mutation's writes persist."""
        savepoint_name, todo_name = self._savepoint_with_todo()

        _finalize_mutation_savepoint(savepoint_name, succeeded=True, debug_info=[])

        self.assertTrue(
            frappe.db.exists("ToDo", todo_name),
            "A succeeded mutation's writes must be kept",
        )
        frappe.delete_doc("ToDo", todo_name, ignore_permissions=True, force=True)

    def test_missing_savepoint_does_not_raise(self):
        """A dropped/missing savepoint is tolerated — it must not abort the batch."""
        debug_info = []
        _finalize_mutation_savepoint(
            f"eb_test_missing_{frappe.generate_hash(length=8)}", succeeded=False, debug_info=debug_info
        )
        self.assertTrue(
            any("SAVEPOINT WARNING" in line for line in debug_info),
            "A missing savepoint should be logged, not raised",
        )
