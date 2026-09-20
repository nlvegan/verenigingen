# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Tests for the Error Log guard (verenigingen.tests.utils.error_log_guard)."""

import ast
import os
import unittest
from unittest.mock import patch

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.error_log_guard import (
    FAIL_ON_ERROR_LOG_ENV,
    fail_on_error_log_enabled,
    format_error_log_failure,
)

PROBE_TITLE = "ErrorLogGuardProbe"


class TestErrorLogGuard(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # Every test here deliberately writes Error Logs with this title; tell the
        # automatic tearDown check to ignore them so this file stays green even when
        # the suite is run with VERENIGINGEN_FAIL_ON_ERROR_LOG=1.
        self.expectErrorLog(PROBE_TITLE)

    def _log_probe(self, message="boom"):
        frappe.log_error(message=message, title=PROBE_TITLE)

    # --- assertNoErrorLog -------------------------------------------------

    def test_passes_when_no_error_logged(self):
        with self.assertNoErrorLog():
            _ = 1 + 1  # exercises nothing that logs

    def test_fails_when_error_logged_inside_block(self):
        with self.assertRaises(AssertionError) as ctx:
            with self.assertNoErrorLog():
                self._log_probe("inside the guarded block")
        self.assertIn("Error Log", str(ctx.exception))

    def test_ignore_pattern_suppresses_failure(self):
        # The probe title is in the ignore set -> guard must NOT fail.
        with self.assertNoErrorLog(ignore=[PROBE_TITLE]):
            self._log_probe("ignored by pattern")

    def test_only_new_logs_count(self):
        # A log written BEFORE the guarded block must not trip the guard.
        self._log_probe("logged before the block")
        with self.assertNoErrorLog(ignore=[PROBE_TITLE]):
            pass
        # And without the ignore the pre-existing one still must not count, because
        # the guard only looks at rows created after it starts.
        self._log_probe("again before a fresh guard")
        with self.assertNoErrorLog():
            pass  # logs the test set the ignore for in setUp; nothing new here

    # --- assertErrorLog -----------------------------------------------------

    def test_assertErrorLog_passes_when_matching_log_written(self):
        with self.assertErrorLog(PROBE_TITLE):
            self._log_probe("this is the log assertErrorLog must see")

    def test_assertErrorLog_fails_when_nothing_logged(self):
        with self.assertRaises(AssertionError) as ctx:
            with self.assertErrorLog(PROBE_TITLE):
                pass  # exercises nothing that logs
        self.assertIn(PROBE_TITLE, str(ctx.exception))

    def test_assertErrorLog_fails_when_pattern_does_not_match(self):
        # A log IS written inside the block, but it does not match the pattern the
        # test asked for -- assertErrorLog must still fail, not treat "some log, any
        # log" as satisfying a specific pattern.
        with self.assertRaises(AssertionError):
            with self.assertErrorLog("SomePatternThatWillNeverMatch"):
                self._log_probe("unrelated log body")

    def test_assertErrorLog_ignores_logs_written_before_the_block(self):
        # tabError Log is MyISAM/non-transactional, so a row written earlier in this
        # test (or an earlier test) survives any rollback. assertErrorLog must scope
        # to rows created INSIDE its own block, not fall back to a bare table count
        # or "any matching row that exists at all" -- otherwise a log from a
        # completely different call would produce a false pass.
        self._log_probe("written before the guarded block even starts")
        with self.assertRaises(AssertionError):
            with self.assertErrorLog(PROBE_TITLE):
                pass  # nothing logged INSIDE this block

    def test_assertErrorLog_custom_message(self):
        with self.assertRaises(AssertionError) as ctx:
            with self.assertErrorLog(PROBE_TITLE, msg="custom failure text"):
                pass
        self.assertIn("custom failure text", str(ctx.exception))

    def test_assertErrorLog_no_pattern_accepts_any_log(self):
        # With no patterns given, any Error Log row written inside the block
        # satisfies the assertion (mirrors assertNoErrorLog's "any row fails it").
        with self.assertErrorLog():
            self._log_probe("no specific pattern requested")

    # --- inertness (#1117): the check must still run when the body raises --

    def test_assertNoErrorLog_still_fires_when_body_raises(self):
        # WRONG nesting (guard innermost) -- this used to be silently inert: the
        # ValueError propagated straight through the bare `yield` and the check
        # after it never ran, so this whole test passed despite a row having been
        # written (#1117). It must now surface the violation instead.
        with self.assertRaises(AssertionError) as ctx:
            with self.assertNoErrorLog():
                self._log_probe("this SHOULD trip assertNoErrorLog")
                raise ValueError("boom")
        self.assertIn("Error Log", str(ctx.exception))
        # The body's exception must not be silently discarded -- it is chained as
        # the cause, so a human (or a `__cause__` check like this one) can still
        # see what actually happened inside the block.
        self.assertIsInstance(ctx.exception.__cause__, ValueError)
        self.assertEqual(str(ctx.exception.__cause__), "boom")

    def test_assertNoErrorLog_lets_a_clean_exception_propagate_unmasked(self):
        # Same WRONG nesting, but nothing was logged -- the guard has nothing to
        # complain about, so the body's own exception must propagate exactly as
        # it would with no guard at all (no masking, no chaining, no swallowing).
        with self.assertRaises(ValueError) as ctx:
            with self.assertNoErrorLog():
                raise ValueError("boom -- nothing was logged")
        self.assertEqual(str(ctx.exception), "boom -- nothing was logged")
        self.assertIsNone(ctx.exception.__cause__)

    def test_assertErrorLog_still_fires_when_body_raises_and_nothing_logged(self):
        # WRONG nesting again: the pattern is never logged AND the body raises.
        # Previously this passed silently (#1117) because the bare `yield` let the
        # ValueError skip the "was anything logged" check entirely.
        with self.assertRaises(AssertionError) as ctx:
            with self.assertErrorLog("A Pattern That Is Never Logged"):
                raise ValueError("boom -- and nothing was logged")
        self.assertIn("A Pattern That Is Never Logged", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, ValueError)

    def test_assertErrorLog_lets_body_exception_propagate_when_satisfied(self):
        # WRONG nesting, but the block DID log a matching row before raising --
        # the assertion's condition is met, so the body's exception must still
        # propagate unmasked (assertErrorLog is not itself an assertRaises).
        with self.assertRaises(ValueError) as ctx:
            with self.assertErrorLog(PROBE_TITLE):
                self._log_probe("logged, then raised")
                raise ValueError("boom -- but it did log")
        self.assertEqual(str(ctx.exception), "boom -- but it did log")
        self.assertIsNone(ctx.exception.__cause__)

    # --- finalize (env-flag) decision ------------------------------------

    def test_finalize_warns_by_default(self):
        self._captured_error_logs = [{"method": PROBE_TITLE, "error": "x", "creation": "now"}]
        with patch.dict(os.environ, {FAIL_ON_ERROR_LOG_ENV: ""}, clear=False):
            self.assertFalse(fail_on_error_log_enabled())
            # Should NOT raise; just warns.
            self._finalize_error_log_check()

    def test_finalize_fails_when_flag_set(self):
        self._captured_error_logs = [{"method": PROBE_TITLE, "error": "x", "creation": "now"}]
        with patch.dict(os.environ, {FAIL_ON_ERROR_LOG_ENV: "1"}, clear=False):
            self.assertTrue(fail_on_error_log_enabled())
            with self.assertRaises(AssertionError):
                self._finalize_error_log_check()
        # reset so our OWN tearDown doesn't re-raise on this captured list
        self._captured_error_logs = []

    def test_finalize_noop_when_nothing_captured(self):
        self._captured_error_logs = []
        with patch.dict(os.environ, {FAIL_ON_ERROR_LOG_ENV: "1"}, clear=False):
            self._finalize_error_log_check()  # must not raise

    # --- helpers ----------------------------------------------------------

    def test_format_failure_message_truncates(self):
        rows = [{"method": f"T{i}", "error": "e", "creation": "now"} for i in range(15)]
        msg = format_error_log_failure(rows)
        self.assertIn("and 5 more", msg)


class TestProductionValidation(VereningingenTestCase):
    """The production_validation() context manager neutralizes frappe.flags.in_import
    so ERPNext's import-only validation suppressions (e.g. validate_due_date's
    self-heal) do NOT mask production behaviour inside the wrapped block."""

    def setUp(self):
        super().setUp()
        self._saved_in_import = getattr(frappe.flags, "in_import", False)
        self.addCleanup(lambda: setattr(frappe.flags, "in_import", self._saved_in_import))

    def test_neutralizes_in_import_inside_block(self):
        frappe.flags.in_import = True
        with self.production_validation():
            self.assertFalse(frappe.flags.in_import)

    def test_restores_prior_true_flag_after_block(self):
        frappe.flags.in_import = True
        with self.production_validation():
            pass
        self.assertTrue(frappe.flags.in_import)

    def test_restores_prior_false_flag_after_block(self):
        frappe.flags.in_import = False
        with self.production_validation():
            self.assertFalse(frappe.flags.in_import)
        self.assertFalse(frappe.flags.in_import)

    def test_restores_flag_on_exception(self):
        frappe.flags.in_import = True
        with self.assertRaises(ValueError):
            with self.production_validation():
                raise ValueError("boom")
        self.assertTrue(frappe.flags.in_import)


# --- #1117 regression gate: a guard nested inside assertRaises -------------
#
# The fix above (try/finally instead of a bare yield) makes assertNoErrorLog()/
# assertErrorLog() run their check regardless of nesting, so this shape can no
# longer produce a silent false pass. This AST sweep is a SEPARATE, narrower
# safety net for the style question the guards' own docstrings still recommend
# (put the guard OUTERMOST, so a mismatch between "raised" and "logged" is
# diagnosed at the layer that saw both): it fails the build the moment a new
# call site nests one of these guards inside `assertRaises`, rather than
# waiting for someone to notice the docstring was ignored. Deliberately scoped
# to this exact pair of names, not every context manager that could swallow --
# broadening it is a separate, larger effort (see the class-sweep note in the
# module docstring above and PR #1117's description for what else was found).
_GUARD_METHOD_NAMES = {"assertNoErrorLog", "assertErrorLog"}
# This file's own tests deliberately nest the guard inside
# `assertRaises(AssertionError)` to assert that the GUARD's own failure fires
# -- the exception being caught there is the guard's, not the wrapped code's.
_ALLOWED_FILENAME = "test_error_log_guard.py"


def _is_guard_call(expr):
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute):
        if expr.func.attr in _GUARD_METHOD_NAMES:
            return expr.func.attr
    return None


def _is_assert_raises_call(expr):
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "assertRaises"
    )


def _find_inert_guard_nestings(root_dir):
    """Return (path, lineno, guard_name) for every guard call whose `with` sits
    lexically inside an enclosing `with self.assertRaises(...):`, anywhere under
    ``root_dir`` -- ``scripts/`` included, since it is live code too (#1117)."""
    hits = []
    skip_dirs = {".git", "node_modules", ".scratch", "__pycache__"}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in filenames:
            if not filename.endswith(".py") or filename == _ALLOWED_FILENAME:
                continue
            path = os.path.join(dirpath, filename)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
            except (SyntaxError, UnicodeDecodeError):
                continue

            assert_raises_depth = []

            class _Visitor(ast.NodeVisitor):
                def visit_With(self, node):  # noqa: N802 - ast visitor naming
                    guard_hits = [
                        (name, item.context_expr.lineno)
                        for item in node.items
                        if (name := _is_guard_call(item.context_expr))
                    ]
                    if guard_hits and assert_raises_depth:
                        for name, lineno in guard_hits:
                            hits.append((path, lineno, name))
                    pushed = sum(
                        1 for item in node.items if _is_assert_raises_call(item.context_expr)
                    )
                    assert_raises_depth.extend([True] * pushed)
                    self.generic_visit(node)
                    del assert_raises_depth[len(assert_raises_depth) - pushed :]

            _Visitor().visit(tree)
    return hits


class TestNoInertGuardNesting(unittest.TestCase):
    """#1117: guard against a NEW call site reintroducing the inert-nesting shape.

    The runtime fix means this nesting is no longer silently inert, but it is
    still a worse diagnostic (the guard's failure masks which exception was
    "the real one") than putting the guard outermost, per both guards'
    docstrings. Catch it mechanically instead of relying on review.
    """

    def test_no_guard_is_nested_inside_assertRaises_outside_this_file(self):
        app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        hits = _find_inert_guard_nestings(app_root)
        self.assertEqual(
            hits,
            [],
            f"Found {len(hits)} call site(s) nesting assertNoErrorLog()/assertErrorLog() "
            "inside assertRaises(...) outside test_error_log_guard.py. Put the guard "
            "OUTERMOST instead (see either guard's docstring): "
            "with self.assertNoErrorLog():\\n    with self.assertRaises(...):\\n        ...\n"
            f"Sites: {hits}",
        )
