"""A savepoint rollback inside an `except` must never replace the error it is cleaning up after (#561).

``ROLLBACK TO SAVEPOINT`` raises 1305 when the savepoint is gone, and a raise from inside an
``except`` block *replaces* the exception being handled. Two things destroy a savepoint for
reasons unrelated to the failure being handled:

* **a 1213 deadlock** -- the server discards the entire transaction, savepoints included;
* **a nested commit** -- any commit clears the savepoint stack, so a helper that commits
  internally takes its caller's savepoint with it.

Either way the 1305 becomes the propagating exception, and every guard keyed on the original
error's TYPE evaluates False. That is how #481's ``except NON_RESUMABLE_DB_ERRORS: raise``
could be correctly placed on 50 endpoints and still never fire (#561), and it is why a
census found 15 production handlers whose FIRST statement was that rollback.

This module holds three different things, and they cover different amounts:

1. the helper's behaviour, against the REAL driver error rather than a stand-in;
2. one end-to-end site, proving a deadlock now arrives as a deadlock;
3. an AST ratchet over every such handler in the app -- which sees SHAPE only.

The ratchet in (3) was, until #1189, reachable ONLY from inside this bench-run suite -- not
referenced by name in ``.pre-commit-config.yaml`` or any workflow, so a violation went
unseen until a specific CI shard finished (it tripped PR #1171 twice this way). Its
scanning logic now lives in ``scripts/validation/savepoint_rollback_validator.py``, a
stdlib-only module with no ``frappe`` import, wired into pre-commit and a dedicated
CI job so it speaks at the author's keyboard instead. ``TestEverySavepointRollbackInAnExcept``
below imports that module's functions rather than keeping its own copy, so there remains
exactly ONE implementation of the scan, reachable both ways.
"""

import ast
import pathlib

import frappe

from scripts.validation.savepoint_rollback_validator import (
    ACCEPTED_SHAPES,
    APP_ROOT,
    EXEMPTION_MARKER,
    PLANTED_OFFENDING_SHAPES,
    offenders as _shared_offenders,
    production_files as _shared_production_files,
)
from verenigingen.tests.support.non_resumable_errors import deadlock, lock_wait_timeout
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS, rollback_to_savepoint

assert APP_ROOT == pathlib.Path(__file__).resolve().parents[2], (
    "scripts/validation/savepoint_rollback_validator.py's APP_ROOT must still resolve to the "
    "verenigingen package directory -- if this fails, the standalone validator and this test "
    "are no longer scanning the same tree."
)


class TestRollbackToSavepoint(VereningingenTestCase):
    """The helper, against the real MySQLdb error rather than a hand-made one."""

    def _savepoint(self):
        name = f"sp_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(name)
        return name

    def test_it_really_rolls_the_write_back_when_the_savepoint_is_there(self):
        """The control, asserting the WRITE rather than the return value.

        Asserting only ``assertTrue(rollback_to_savepoint(...))`` does not discriminate:
        replacing the body with ``pass; return True`` leaves that green, so it would be
        equally consistent with the helper never rolling anything back at all.
        """
        tag = frappe.generate_hash(length=10)
        name = self._savepoint()
        frappe.db.set_value("DocType", "ToDo", "description", tag, update_modified=False)
        self.assertEqual(frappe.db.get_value("DocType", "ToDo", "description"), tag)

        self.assertTrue(rollback_to_savepoint(name), "a live savepoint must be rolled back")

        self.assertNotEqual(
            frappe.db.get_value("DocType", "ToDo", "description"),
            tag,
            "the write made after the savepoint must be gone",
        )

    def test_it_reports_a_savepoint_that_is_already_gone_instead_of_raising(self):
        """The real 1305, produced by the real driver.

        Releasing the savepoint reproduces what a 1213 and a nested commit both leave
        behind, without a ROLLBACK that would take the test's own fixtures with it.
        """
        name = self._savepoint()
        frappe.db.sql(f"RELEASE SAVEPOINT {name}")

        # Prove the premise rather than assuming it: this really does raise 1305 today.
        with self.assertRaises(Exception) as caught:
            frappe.db.rollback(save_point=name)
        self.assertIn("does not exist", str(caught.exception))

        self.assertFalse(
            rollback_to_savepoint(name), "a missing savepoint is reported, not raised"
        )

    def test_it_still_raises_anything_that_is_not_a_missing_savepoint(self):
        """It hides one diagnosed condition, not savepoint bugs in general."""
        original = frappe.local.db.rollback

        def _boom(*, save_point=None, chain=False):
            raise RuntimeError("connection went away")

        frappe.local.db.rollback = _boom
        self.addCleanup(frappe.local.db.__dict__.pop, "rollback", None)

        with self.assertRaises(RuntimeError):
            rollback_to_savepoint("whatever")

    def test_the_original_error_survives_the_cleanup(self):
        """The whole point, stated as the invariant rather than as a mechanism.

        Before #561 this block re-raised 1305 and the deadlock was gone.
        """
        name = self._savepoint()
        frappe.db.sql(f"RELEASE SAVEPOINT {name}")

        with self.assertRaises(Exception) as caught:
            try:
                raise deadlock()
            except Exception:
                rollback_to_savepoint(name)
                raise

        self.assertIsInstance(caught.exception, frappe.QueryDeadlockError)


class TestAPollingRowAbandonsOnANonResumableError(VereningingenTestCase):
    """One production site, driven for real. The ratchet below cannot see any of this.

    ``MijnRoodPollingService._row_savepoint`` wraps each row in its own savepoint so one
    bad row does not poison the table -- deliberate, documented, and right for an ordinary
    failure. On a 1205/1213 it was wrong twice over: the scan carried on against a
    transaction the server had discarded, and the 1305 from its own rollback replaced the
    error on the way out.
    """

    def _open_row_savepoint(self, stats):
        from verenigingen.mijnrood_sync.services.polling_service import MijnRoodPollingService

        return MijnRoodPollingService()._row_savepoint("row-1", "members", stats)

    def _capture_savepoint_names(self):
        taken = []
        real = frappe.local.db.savepoint

        def _recording(save_point):
            taken.append(save_point)
            return real(save_point)

        frappe.local.db.savepoint = _recording
        self.addCleanup(frappe.local.db.__dict__.pop, "savepoint", None)
        return taken

    def test_an_ordinary_row_failure_is_still_swallowed_so_the_batch_continues(self):
        """The control. Without it, the two tests below would also pass if per-row
        isolation had been removed altogether."""
        stats = {}
        with self._open_row_savepoint(stats):
            raise ValueError("one bad row")

        self.assertEqual(stats["errors"], 1, "an ordinary row failure is counted and skipped")

    def test_a_deadlock_abandons_the_scan_instead_of_counting_it_as_one_bad_row(self):
        stats = {}
        with self.assertRaises(frappe.QueryDeadlockError):
            with self._open_row_savepoint(stats):
                raise deadlock()

        self.assertEqual(
            stats.get("errors", 0),
            0,
            "a transaction the server discarded is not a row error to tally and move past",
        )

    def test_a_lock_timeout_abandons_the_scan_too(self):
        stats = {}
        with self.assertRaises(frappe.QueryTimeoutError):
            with self._open_row_savepoint(stats):
                raise lock_wait_timeout()

        self.assertEqual(stats.get("errors", 0), 0)

    def test_a_destroyed_savepoint_does_not_replace_the_row_error(self):
        """The masking half, at a real site.

        Releasing the savepoint reproduces what a 1213 and a nested commit both leave
        behind. Before #561 the handler's own ``rollback(save_point=...)`` raised 1305 out
        of the context manager, so a row failure the caller had chosen to tolerate became
        an unhandled error about a savepoint.
        """
        taken = self._capture_savepoint_names()
        stats = {}
        with self._open_row_savepoint(stats):
            frappe.db.sql(f"RELEASE SAVEPOINT {taken[-1]}")
            raise ValueError("one bad row, and the savepoint is gone")

        self.assertEqual(stats["errors"], 1, "the row failure is still what gets counted")


class TestEverySavepointRollbackInAnExcept(VereningingenTestCase):
    """The ratchet. 15 handlers were fixed; this is what stops the sixteenth.

    Scoped to every production handler in the app rather than one package, because the
    census for #561 read all of them -- a narrower scope would leave the rest exactly as
    they were when the same trap was documented in PR #169 and then recurred 15 times.

    Two rules, and it enforces SHAPE only:

    1. a broad handler whose body rolls back to a savepoint must be preceded by
       ``except NON_RESUMABLE_DB_ERRORS:`` whose body is a bare ``raise``;
    2. the rollback itself must go through ``rollback_to_savepoint()``, because rule 1
       does not cover the nested-commit cause -- that arrives as an ordinary exception.

    Both rules originally matched only ``frappe.db.rollback(save_point=...)``. Two sites
    (vip_import.py, member_import_service.py) instead hand-wrote the raw SQL --
    ``frappe.db.sql("ROLLBACK TO SAVEPOINT ...")`` -- which is a ``.sql(...)`` call, not a
    ``.rollback(save_point=...)`` call, so they survived this ratchet entirely despite its
    docstring's claim to cover "every such handler" (#701). ``bare_savepoint_rollbacks``,
    ``_is_savepoint_only`` and ``rolls_back_a_savepoint`` (in the shared module) now match
    either spelling.

    **What it cannot see:** whether a guarded handler then reports the error usefully, and
    whether an exemption's stated reason is true. Both stay human claims. Read that before
    reading a green run here as coverage of behaviour.

    The scan itself (``_offenders`` and everything it calls) is NOT defined here -- it is
    imported from ``scripts/validation/savepoint_rollback_validator.py`` (#1189), which is
    also the standalone, pre-commit-invokable entry point for this same ratchet. This class
    is the second of its two entry points, not a second implementation.
    """

    def test_no_savepoint_rollback_can_mask_the_error_it_is_cleaning_up_after(self):
        offenders = []
        for path in _shared_production_files():
            source = path.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for lineno, why in _shared_offenders(source, tree):
                offenders.append(f"{path.relative_to(APP_ROOT)}:{lineno} -- {why}")

        self.assertEqual(
            offenders,
            [],
            "a 1213 (and any nested commit) destroys the savepoint, so these rollbacks raise "
            "1305 from inside the handler and REPLACE the error being handled (#561). Use "
            "`rollback_to_savepoint()` from utils.transaction_errors, put "
            "`except NON_RESUMABLE_DB_ERRORS: raise` above the catch-all, or mark the handler "
            f"`# {EXEMPTION_MARKER} <reason>` if it runs after the failure:\n  "
            + "\n  ".join(offenders),
        )

    def test_the_ratchet_sees_the_shapes_the_app_no_longer_contains(self):
        """A synthetic positive control. Once the app is clean the test above passes on an
        empty list -- which is also what a walker that silently matched nothing produces.
        Every branch below is unreachable from the real files."""
        planted = PLANTED_OFFENDING_SHAPES
        for label, (snippet, expected) in planted.items():
            with self.subTest(label):
                found = list(_shared_offenders(snippet, ast.parse(snippet)))
                self.assertEqual(
                    len(found), expected, f"{label}: expected {expected} findings, got {found}"
                )

        accepted = ACCEPTED_SHAPES
        for label, snippet in accepted.items():
            with self.subTest(label):
                self.assertEqual(
                    list(_shared_offenders(snippet, ast.parse(snippet))), [], f"{label} must be accepted"
                )

    def test_the_two_error_classes_it_names_are_the_ones_that_exist(self):
        """Guards against the tuple being renamed out from under the ratchet's string match."""
        self.assertEqual(
            NON_RESUMABLE_DB_ERRORS, (frappe.QueryDeadlockError, frappe.QueryTimeoutError)
        )
        self.assertIsInstance(deadlock(), frappe.QueryDeadlockError)
        self.assertIsInstance(lock_wait_timeout(), frappe.QueryTimeoutError)
