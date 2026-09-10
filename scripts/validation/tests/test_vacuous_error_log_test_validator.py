#!/usr/bin/env python3
"""Unit tests for scripts/validation/vacuous_error_log_test_validator.py.

Pure-Python (no bench/site needed): each case is a source snippet written to a
temp file and run through scan_file(). Run with:
    python -m unittest discover -s scripts/validation/tests \
        -p 'test_vacuous_error_log_test_validator.py'


Pins the rule #1112 asked for: a test whose NAME claims an Error Log write,
which declares ``self.expectErrorLog(...)`` and asserts nothing about the
log, cannot fail for the reason it exists. #1116 converted 17 such tests and
renamed a 18th; nothing stopped the 19th from arriving, which is what this
validator is for.

The control that matters is ``test_the_historical_1112_shape_is_flagged``:
it reproduces the exact shape of the two instances #1112 confirmed by hand,
so the validator is pinned against a defect that really existed rather than
only against one invented here.
"""

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "vacuous_error_log_test_validator.py"
_spec = importlib.util.spec_from_file_location("vacuous_error_log_test_validator", _MOD_PATH)
v = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v
_spec.loader.exec_module(v)


class TestVacuousErrorLogTestValidator(unittest.TestCase):
    def _write(self, source: str) -> Path:
        fd = tempfile.NamedTemporaryFile(
            mode="w", prefix="test_", suffix=".py", delete=False, encoding="utf-8"
        )
        fd.write(textwrap.dedent(source))
        fd.close()
        path = Path(fd.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def _names(self, source: str):
        findings, _bad = v.scan_file(self._write(source))
        return [f.test for f in findings]

    # ------------------------------------------------------------------
    # the shape the gate exists for
    # ------------------------------------------------------------------

    def test_the_historical_1112_shape_is_flagged(self):
        """The exact shape of #1112's two confirmed instances.

        Reproduced from test_page_payment_success_coverage.py as it stood at
        c37e65738: a name claiming a security Error Log write, an
        expectErrorLog() declaration that only mutes the harness, and no
        assertion of any kind about the log.
        """
        self.assertEqual(
            self._names(
                '''
                class TestPage(EnhancedTestCase):
                    def test_validate_disallowed_doctype_logs_security_event(self):
                        """A disallowed doctype is rejected AND writes a security Error Log."""
                        self.expectErrorLog("Payment Status Security")
                        is_valid, result = payment_success.validate_payment_document_access(
                            "ToDo", "anything", "tr_x"
                        )
                        self.assertFalse(is_valid)
                        self.assertIsInstance(result, str)
                '''
            ),
            ["test_validate_disallowed_doctype_logs_security_event"],
        )

    # ------------------------------------------------------------------
    # what must NOT be flagged
    # ------------------------------------------------------------------

    def test_assert_error_log_is_sound(self):
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def test_rejection_logs_security_event(self):
                        self.expectErrorLog("Sec")
                        with self.assertErrorLog("Sec"):
                            do_it()
                """
            ),
            [],
        )

    def test_assert_no_error_log_is_sound(self):
        """An explicit negative assertion is still an assertion about the log."""
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def test_mismatch_writes_no_error_log(self):
                        self.expectErrorLog("Sec")
                        with self.assertNoErrorLog():
                            do_it()
                """
            ),
            [],
        )

    def test_direct_error_log_query_is_sound(self):
        """The shape ~45 of #1116's already-sound candidates use."""
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def test_failure_logs_the_error(self):
                        self.expectErrorLog("Sec")
                        before = frappe.db.count("Error Log", {"error": ["like", "%x%"]})
                        do_it()
                        self.assertGreater(frappe.db.count("Error Log", {"error": ["like", "%x%"]}), before)
                """
            ),
            [],
        )

    def test_raw_sql_against_taberror_log_is_sound(self):
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def test_failure_logs_the_error(self):
                        self.expectErrorLog("Sec")
                        rows = frappe.db.sql("SELECT name FROM `tabError Log` WHERE error LIKE %s", ("%x%",))
                        self.assertTrue(rows)
                """
            ),
            [],
        )

    def test_without_expect_error_log_is_out_of_scope(self):
        """No expectErrorLog means the harness's automatic check is live.

        Such a test cannot silently pass while a row is written -- tearDown
        fails it -- so it is a different (and unmeasured) class, deliberately
        not this gate's business.
        """
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def test_failure_logs_the_error(self):
                        do_it()
                        self.assertTrue(True)
                """
            ),
            [],
        )

    def test_name_not_claiming_a_log_is_not_flagged(self):
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def test_rejects_a_forged_token(self):
                        self.expectErrorLog("Sec")
                        do_it()
                """
            ),
            [],
        )

    def test_non_test_method_is_not_flagged(self):
        """A helper named ..._logs_... is not a test and cannot be vacuous."""
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def helper_that_logs_something(self):
                        self.expectErrorLog("Sec")
                """
            ),
            [],
        )

    # ------------------------------------------------------------------
    # escape hatch
    # ------------------------------------------------------------------

    def test_pragma_suppresses(self):
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def test_failure_logs_the_error(self):  # vacuous-log-test-ok: false-positive
                        self.expectErrorLog("Sec")
                        do_it()
                """
            ),
            [],
        )

    def test_pragma_with_invalid_reason_is_reported(self):
        _findings, bad = v.scan_file(
            self._write(
                """
                class T(EnhancedTestCase):
                    def test_failure_logs_the_error(self):  # vacuous-log-test-ok: because
                        self.expectErrorLog("Sec")
                        do_it()
                """
            )
        )
        self.assertEqual(len(bad), 1)
        self.assertIn("because", bad[0][1])

    # ------------------------------------------------------------------
    # the tree itself
    # ------------------------------------------------------------------

    def test_the_repository_is_clean(self):
        """Zero-tolerance: #1116 and #1103 fixed every instance, so 0 is the floor.

        This validator carries no baseline file deliberately -- there is
        nothing left to baseline, and a baseline would be both new ratchet
        debt (#985) and exposure to the shrink-gate defect in #1110.
        """
        findings = v.scan(v.default_paths())
        self.assertEqual(
            [f"{f.file}::{f.test}" for f in findings],
            [],
            "A vacuous log-claiming test has been (re)introduced; see #1112.",
        )


if __name__ == "__main__":
    unittest.main()
