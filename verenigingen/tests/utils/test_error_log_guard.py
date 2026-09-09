# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Tests for the Error Log guard (verenigingen.tests.utils.error_log_guard)."""

import os
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
