"""Real-DB savepoint tests for `migration_transaction` (#701).

`test_migration_transaction.py` mocks `security_helper.frappe` entirely, so its
two savepoint-rollback tests were patched (this PR) to assert against the
canonical `rollback_to_savepoint()` / `release_savepoint_if_present()` helper
calls instead of the raw SQL strings that no longer exist. But mocking `frappe`
cannot exercise what those helpers actually DO against a real destroyed
savepoint, and `atomic_migration_operation` (the sibling context manager in the
same file) already got that real-DB coverage in
`test_atomic_migration_operation_savepoints.py`. This file closes that
asymmetry for `migration_transaction`.

It also directly proves the fix for the `finally:`-block risk found in review.
Python's exception-replacement mechanics do not differ between `except:` and
`finally:` -- a raise from either replaces whatever was already propagating,
identically. What differs is EXPOSURE: this `finally:` runs on every exit path,
including the SUCCESS path, where nothing is propagating at all. An unhandled
cleanup failure there would not just replace an already-failing outcome (the
accepted, documented tradeoff every other caller of these helpers relies on
from inside `except` blocks); it would turn a SUCCESSFUL transaction into a
reported failure. That is why this one call keeps a protective wrapper the
`except`-block sites do not need, and now records what it catches via
`frappe.log_error` rather than swallowing it silently (#701 second review
round -- the AST ratchet and `error_swallow_validator.py` were both blind to a
bare-name call to the canonical helper wrapped in its own try/except, wherever
it appeared; the ratchet was widened to see it and the site is now marked
`# non-resumable-ok:`).
`test_a_genuinely_unexpected_cleanup_failure_does_not_clobber_the_original_error`
proves the original-error-survives half; that same test's mutation now also
produces a real Error Log row (`setUp`/`tearDown` below sweep it, the same
technique `test_migration_transaction.py` uses -- `tabError Log` is MyISAM, so
a plain `frappe.db.rollback()` would not remove it).

Run with:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_transaction_savepoints
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.e_boekhouden.utils import security_helper
from verenigingen.tests.support.attr_patching import patch_db_rollback, patch_module_attr


class TestMigrationTransactionSavepoints(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # test_a_destroyed_savepoint_does_not_replace_the_original_error and
        # test_a_genuinely_unexpected_cleanup_failure_does_not_clobber_the_original_error
        # both drive real Error Log inserts (rollback_to_savepoint's tolerated-1305
        # path, and the new #701 cleanup-failure log_error respectively). Mark the
        # start so tearDown can sweep them -- `tabError Log` is MyISAM
        # (non-transactional), so a plain frappe.db.rollback() would not remove them.
        self._error_log_marker = frappe.utils.now_datetime()

    def tearDown(self):
        frappe.db.delete("Error Log", {"creation": (">=", self._error_log_marker)})
        frappe.db.commit()
        super().tearDown()

    def test_rolls_back_on_an_ordinary_failure(self):
        """Control: the savepoint is intact, so the write made inside the
        context is undone. Without this, the tests below would also pass if the
        rollback had been removed altogether."""
        tag = frappe.generate_hash(length=10)

        with self.assertRaises(ValueError):
            with security_helper.migration_transaction(operation_type="account_creation") as tx:
                frappe.db.set_value("DocType", "ToDo", "description", tag, update_modified=False)
                tx.track_operation("create", "doc1")
                raise ValueError("boom")

        self.assertNotEqual(
            frappe.db.get_value("DocType", "ToDo", "description"),
            tag,
            "the write made inside the failed transaction must be rolled back",
        )

    def test_a_destroyed_savepoint_does_not_replace_the_original_error(self):
        """Reproduces what a 1213 deadlock or a nested commit leaves behind: the
        savepoint is gone by the time the `except` handler tries to roll back to
        it.

        Releasing it directly is the same technique
        `test_savepoint_rollback_cannot_mask_the_error.py` uses to reproduce a
        real 1305 from the real driver, without a ROLLBACK that would also take
        the test's own fixtures with it.
        """
        with self.assertRaises(ValueError) as caught:
            with security_helper.migration_transaction(operation_type="account_creation") as tx:
                tx.track_operation("create", "doc1")
                # Simulate the savepoint already being gone (a 1213/nested
                # commit) before the handler ever tries to roll back to it.
                frappe.db.sql("RELEASE SAVEPOINT migration_start")
                raise ValueError("the real reason this transaction failed")

        self.assertEqual(
            str(caught.exception),
            "the real reason this transaction failed",
            "the destroyed savepoint's own 1305 must not replace the real error",
        )

    def test_a_deadlock_reraises_directly_without_attempting_a_savepoint_rollback(self):
        """A 1213 discards the WHOLE transaction, not just this operation --
        there is nothing left for `rollback_to_savepoint` to roll back to, so it
        must never even be called."""
        calls = []
        original = security_helper.rollback_to_savepoint

        def recording_rollback_to_savepoint(name):
            calls.append(name)
            return original(name)

        with patch_module_attr(security_helper, "rollback_to_savepoint", recording_rollback_to_savepoint):
            with self.assertRaises(frappe.QueryDeadlockError):
                with security_helper.migration_transaction(operation_type="account_creation") as tx:
                    tx.track_operation("create", "doc1")
                    raise frappe.QueryDeadlockError(
                        "Deadlock found when trying to get lock; try restarting transaction"
                    )

        self.assertEqual(
            calls,
            [],
            "a 1213 must not attempt a savepoint rollback -- there is nothing left to roll back to",
        )

    def test_a_genuinely_unexpected_cleanup_failure_does_not_clobber_the_original_error(self):
        """The finally-block risk found in review: `migration_transaction`'s
        cleanup calls `release_savepoint_if_present()` from a bare `finally:`,
        and a `finally:` that raises ALWAYS replaces whatever exception was
        already propagating -- unlike an `except` block, where a bare `raise`
        re-raises the SAME exception currently being handled. Simulate a
        genuinely unexpected (non-1305) failure from that cleanup call and
        confirm the ORIGINAL ValueError still survives it, proving the
        protective `except Exception: pass` this PR kept around that one call
        actually does its job.
        """

        def _boom(name):
            raise RuntimeError("connection went away")

        with patch_module_attr(security_helper, "release_savepoint_if_present", _boom):
            with self.assertRaises(ValueError) as caught:
                with security_helper.migration_transaction(operation_type="account_creation") as tx:
                    tx.track_operation("create", "doc1")
                    raise ValueError("the real reason this transaction failed")

        self.assertEqual(
            str(caught.exception),
            "the real reason this transaction failed",
            "an unrelated cleanup failure in the finally: block must not replace the original error",
        )

    def test_rollback_to_savepoint_and_full_rollback_are_not_both_attempted(self):
        """Sanity check on the two rollback paths being mutually exclusive: when
        a savepoint exists, migration_transaction must roll back to it rather
        than issuing a full `frappe.db.rollback()` -- the two are alternatives,
        not a belt-and-suspenders pair, so a real destroyed-savepoint scenario
        should never trigger both."""
        original_rollback = frappe.db.rollback
        rollback_calls = []

        def recording_rollback(*args, **kwargs):
            rollback_calls.append((args, kwargs))
            return original_rollback(*args, **kwargs)

        with patch_db_rollback(recording_rollback):
            with self.assertRaises(ValueError):
                with security_helper.migration_transaction(operation_type="account_creation") as tx:
                    tx.track_operation("create", "doc1")
                    raise ValueError("boom")

        self.assertEqual(
            len(rollback_calls),
            1,
            f"expected exactly one savepoint-scoped rollback, got: {rollback_calls}",
        )
        self.assertEqual(rollback_calls[0][1].get("save_point"), "migration_start")
