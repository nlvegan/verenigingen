# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""
Error Log guard for the Verenigingen test suite.

WHY THIS EXISTS
---------------
Verenigingen production code logs-and-swallows pervasively: a code path catches an
exception, calls ``frappe.log_error(...)``, and returns ``None`` / continues instead
of raising. There are ~2,150 ``frappe.log_error`` call sites across ~480 non-test
modules. The failure mode this creates for tests:

    A test exercises a broken code path -> production code catches the failure and
    writes an Error Log -> the test asserts on the (now-empty / fallback) return
    value -> the test PASSES GREEN while a real bug silently logged an error.

This mixin closes that gap two ways:

1. An automatic, opt-in-to-fail check wired into both base test classes' tearDown.
   By default it only WARNS (preserving historical behaviour). Set the environment
   variable ``VERENIGINGEN_FAIL_ON_ERROR_LOG=1`` to make any Error Log written during
   a test fail that test. This lets the rollout be controlled (CI job, local run).

2. An explicit ``assertNoErrorLog()`` context manager that fails REGARDLESS of the
   env flag, so a sweep / new test can assert a specific block logs nothing.

CAVEAT
------
``frappe.log_error()`` normally does a plain ``insert()`` in the current transaction,
so a same-connection query sees it immediately (read-your-own-writes) -- which is why
the capture MUST happen before tearDown's rollback. The one path this does NOT catch
is ``log_error(..., defer_insert=True)`` or logging while ``frappe.flags.read_only``
is set: those queue to Redis and flush after the request, so they are invisible to an
in-process query. That is an accepted, documented limitation.
"""

import os
from contextlib import contextmanager

import frappe

from verenigingen.tests.harness_logger import get_harness_logger

# Environment variable that flips the automatic tearDown check from warn -> fail.
FAIL_ON_ERROR_LOG_ENV = "VERENIGINGEN_FAIL_ON_ERROR_LOG"

# Substrings that are ALWAYS ignored by the guard (framework noise that is not a
# product error). Keep this list conservative -- anything added here hides real
# errors from every test. Prefer per-test ``expectErrorLog(...)`` over editing this.
DEFAULT_IGNORE_PATTERNS = ()

_TRUTHY = {"1", "true", "yes", "on"}


def fail_on_error_log_enabled() -> bool:
    """Return True when the automatic tearDown check should FAIL (not just warn)."""
    return str(os.environ.get(FAIL_ON_ERROR_LOG_ENV, "")).strip().lower() in _TRUTHY


def _row_matches(row, patterns) -> bool:
    """True if any ``pattern`` appears in the row's method (title) or error body."""
    haystack = f"{row.get('method') or ''}\n{row.get('error') or ''}"
    return any(pattern in haystack for pattern in patterns)


def format_error_log_failure(rows, prefix=None) -> str:
    """Human-readable summary of unexpected Error Log rows for an assertion message."""
    header = prefix or f"{len(rows)} unexpected Error Log entr{'y' if len(rows) == 1 else 'ies'} during test"
    lines = [header]
    for row in rows[:10]:
        title = (row.get("method") or "Error").splitlines()[0][:120]
        body = (row.get("error") or "").strip().replace("\n", " ")[:300]
        lines.append(f"  - [{row.get('creation')}] {title}: {body}")
    if len(rows) > 10:
        lines.append(f"  ... and {len(rows) - 10} more")
    lines.append(
        "  (wrap intentional error-logging in `with self.assertRaises(...)`/`self.expectErrorLog(...)`,"
        " or fix the swallowed error)"
    )
    return "\n".join(lines)


class ErrorLogGuardMixin:
    """
    Adds Error Log detection to a test case.

    The concrete base class is responsible for calling, in its own tearDown:
      * ``self._capture_test_error_logs()`` -- FIRST, before any rollback, and
      * ``self._finalize_error_log_check()`` -- LAST, after cleanup, so a raised
        failure does not skip teardown cleanup.

    It must also set ``self._test_start_time`` (a ``frappe.utils.now()`` string) in
    setUp; if it is missing the check is a no-op.
    """

    def expectErrorLog(self, *patterns):
        """Mark substrings as expected so the AUTOMATIC tearDown check ignores matching
        Error Log rows for the remainder of this test. This does NOT relax an explicit
        ``assertNoErrorLog()`` block -- pass that block its own ``ignore=`` instead."""
        existing = list(getattr(self, "_expected_error_log_patterns", ()))
        existing.extend(patterns)
        self._expected_error_log_patterns = tuple(existing)

    def _ignored_patterns(self, extra=None, *, use_expected=True):
        # ``use_expected`` folds in the per-test expectErrorLog() set. The automatic
        # tearDown check honours it; the explicit assertNoErrorLog() does NOT, so an
        # expected title still trips an assertion deliberately wrapped around a block.
        expected = tuple(getattr(self, "_expected_error_log_patterns", ())) if use_expected else ()
        return tuple(DEFAULT_IGNORE_PATTERNS) + expected + tuple(extra or ())

    def _error_logs_since(self, start, *, ignore=None, before_names=None, use_expected=True):
        """Return Error Log rows created at/after ``start`` (a datetime or now-string),
        excluding any name in ``before_names`` and any matching an ignore pattern."""
        if not start:
            return []
        rows = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", start]},
            fields=["name", "method", "error", "creation"],
            order_by="creation desc",
        )
        if before_names:
            rows = [r for r in rows if r.name not in before_names]
        patterns = self._ignored_patterns(ignore, use_expected=use_expected)
        if patterns:
            rows = [r for r in rows if not _row_matches(r, patterns)]
        return rows

    @contextmanager
    def assertNoErrorLog(self, *, ignore=None, msg=None):
        """Fail if the wrapped block writes any (non-ignored) Error Log row.

        Unlike the automatic tearDown check this ALWAYS fails -- it does not depend on
        the ``VERENIGINGEN_FAIL_ON_ERROR_LOG`` env var. Use it around the specific call
        a test exercises::

            with self.assertNoErrorLog():
                result = some_module.do_the_thing(member)
            self.assertEqual(result.status, "ok")
        """
        marker = frappe.utils.now_datetime()
        before = {
            r.name for r in frappe.get_all("Error Log", filters={"creation": [">=", marker]}, fields=["name"])
        }
        yield
        new = self._error_logs_since(marker, ignore=ignore, before_names=before, use_expected=False)
        if new:
            self.fail(format_error_log_failure(new, prefix=msg))

    @contextmanager
    def production_validation(self):
        """Run the wrapped block with ``frappe.flags.in_import`` forced ``False`` so
        ERPNext's import-only validation suppressions do NOT mask production behaviour.

        ``EnhancedTestCase.setUp`` sets ``frappe.flags.in_import = True`` to bypass
        user-creation throttling. As a side effect ERPNext skips/self-heals several
        validations whenever ``in_import`` is set -- most consequentially
        ``validate_due_date()`` (accounts_controller.py), which silently clamps a
        ``due_date`` that falls before ``posting_date`` instead of raising. That hid a
        real retroactive-billing bug from the ENTIRE suite (the dues invoice generator
        emitted a past due_date; ERPNext logged-and-swallowed it 641x; see commit
        6efbaf41). Production invoice generation runs with ``in_import`` False.

        Wrap any submission/validation you want to mirror production in this block::

            with self.production_validation():
                invoice = schedule.generate_invoice(force=True)
            self.assertGreaterEqual(getdate(invoice.due_date), getdate(invoice.posting_date))

        Restores the prior flag value on exit, including on exception. Note: with the
        flag off, user-creation throttling is back in effect, so do not create Users
        inside the block -- only wrap the operation whose validation you care about.
        """
        saved = getattr(frappe.flags, "in_import", False)
        frappe.flags.in_import = False
        try:
            yield
        finally:
            frappe.flags.in_import = saved

    # --- hooks the concrete base class wires into its tearDown ---------------

    def _capture_test_error_logs(self):
        """Snapshot Error Log rows created during this test. MUST be called at the top
        of tearDown, before any rollback (an uncommitted log_error is erased by it)."""
        try:
            self._captured_error_logs = self._error_logs_since(getattr(self, "_test_start_time", None))
        except Exception as e:  # never let the guard's own bookkeeping break a test
            # get_harness_logger, NOT frappe.logger(): the latter writes only to
            # logs/frappe.log, which CI does not surface -- so a guard that had
            # stopped capturing anything would say so nowhere (#433).
            get_harness_logger("error-log-guard").error("Error Log guard capture failed: %s", e)
            self._captured_error_logs = []

    def _finalize_error_log_check(self):
        """Warn, or fail when the env flag is set, on captured Error Log rows. MUST be
        called at the END of tearDown so cleanup still runs before any raise."""
        rows = getattr(self, "_captured_error_logs", None)
        if not rows:
            return
        summary = format_error_log_failure(
            rows, prefix=f"Errors logged during test {getattr(self, '_testMethodName', '?')}"
        )
        if fail_on_error_log_enabled():
            raise AssertionError(summary)
        # No logger call here on purpose: the `print` below is what a CI reader
        # actually sees. A bare `frappe.logger().error(summary)` used to sit above
        # it, writing the same string a second time to logs/frappe.log -- which CI
        # does not upload -- so it was invisible duplication (#485).
        print(f"WARNING: {summary}")
