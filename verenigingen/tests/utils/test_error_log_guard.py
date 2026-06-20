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
