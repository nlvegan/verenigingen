"""Tests for `atomic_migration_operation`'s savepoint handling (#701).

Before #701 this rolled back with a hand-written `frappe.db.sql("ROLLBACK TO
SAVEPOINT ...")` / `frappe.db.sql("RELEASE SAVEPOINT ...")` pair wrapped in its own
`except Exception: ... frappe.db.rollback()` fallback -- the raw-SQL spelling that
let this file (and vip_import.py, member_import_service.py) survive the AST ratchet
in `test_savepoint_rollback_cannot_mask_the_error.py` entirely, since that ratchet
only recognised `frappe.db.rollback(save_point=...)`.

It now goes through the canonical `rollback_to_savepoint()` / `release_savepoint_if_present()`
helpers from `utils.transaction_errors`, with `except NON_RESUMABLE_DB_ERRORS: raise`
above the catch-all. These tests exercise the real function against the real
database (no mocking of `frappe`), the same way the sibling fixes for vip_import.py
and member_import_service.py were verified.

Run with:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_atomic_migration_operation_savepoints
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.e_boekhouden.utils import security_helper
from verenigingen.tests.support.attr_patching import patch_db_rollback, patch_module_attr


class TestAtomicMigrationOperationSavepoints(FrappeTestCase):
    def test_rolls_back_on_an_ordinary_failure(self):
        """Control: the savepoint is intact, so the write made inside the
        context is undone. Without this, the two tests below would also pass
        if the rollback had been removed altogether."""
        tag = frappe.generate_hash(length=10)

        with self.assertRaises(ValueError):
            with security_helper.atomic_migration_operation("payment_processing"):
                frappe.db.set_value("DocType", "ToDo", "description", tag, update_modified=False)
                raise ValueError("boom")

        self.assertNotEqual(
            frappe.db.get_value("DocType", "ToDo", "description"),
            tag,
            "the write made inside the failed operation must be rolled back",
        )

    def test_a_destroyed_savepoint_falls_back_to_a_full_rollback_without_masking_the_error(self):
        """Reproduces what a 1213 deadlock or a nested commit leaves behind: the
        savepoint is gone by the time the handler tries to roll back to it.

        Releasing it directly is the same technique
        `test_savepoint_rollback_cannot_mask_the_error.py` uses to reproduce a real
        1305 from the real driver, without a ROLLBACK that would also take the
        test's own fixtures with it.

        Before #701, the un-canonicalised code already avoided masking here (the
        hand-written rollback was wrapped in its own try/except with a bare
        `raise` after it) -- this proves the canonical helper preserves that,
        rather than regressing it.
        """
        original_rollback = frappe.db.rollback
        rollback_calls = []

        def recording_rollback(*args, **kwargs):
            rollback_calls.append((args, kwargs))
            return original_rollback(*args, **kwargs)

        with patch_db_rollback(recording_rollback):
            with self.assertRaises(ValueError) as caught:
                with security_helper.atomic_migration_operation("payment_processing"):
                    # Simulate the savepoint already being gone (a 1213/nested
                    # commit) before the handler ever tries to roll back to it.
                    frappe.db.sql("RELEASE SAVEPOINT atomic_migration")
                    raise ValueError("the real reason this operation failed")

        self.assertEqual(
            str(caught.exception),
            "the real reason this operation failed",
            "the destroyed savepoint's own 1305 must not replace the real error",
        )
        # `assertTrue(rollback_calls, ...)` does not discriminate here:
        # `rollback_to_savepoint`'s OWN internal `frappe.db.rollback(save_point=...)`
        # attempt fires unconditionally and is already one entry, regardless of
        # whether the full-rollback fallback below it ever runs. Deleting the
        # fallback (`frappe.db.rollback()` in the `else:` branch of
        # `atomic_migration_operation`) left this assertion green with exactly one
        # call recorded -- the wrong one. Assert the specific fallback shape: a
        # bare `frappe.db.rollback()` call with no arguments, distinct from the
        # `save_point=...` call `rollback_to_savepoint` always makes first.
        self.assertEqual(
            len(rollback_calls),
            2,
            f"expected the internal savepoint attempt plus the full-rollback fallback, "
            f"got: {rollback_calls}",
        )
        self.assertIn(
            ((), {}),
            rollback_calls,
            "the full-rollback fallback (frappe.db.rollback() with no arguments) must actually run",
        )

    def test_a_deadlock_reraises_directly_without_attempting_a_savepoint_rollback(self):
        """A 1213 discards the WHOLE transaction, not just this operation -- there
        is nothing left for `rollback_to_savepoint` to roll back to, so it must
        never even be called."""
        calls = []
        original = security_helper.rollback_to_savepoint

        def recording_rollback_to_savepoint(name):
            calls.append(name)
            return original(name)

        with patch_module_attr(security_helper, "rollback_to_savepoint", recording_rollback_to_savepoint):
            with self.assertRaises(frappe.QueryDeadlockError):
                with security_helper.atomic_migration_operation("payment_processing"):
                    raise frappe.QueryDeadlockError(
                        "Deadlock found when trying to get lock; try restarting transaction"
                    )

        self.assertEqual(
            calls,
            [],
            "a 1213 must not attempt a savepoint rollback -- there is nothing left to roll back to",
        )
