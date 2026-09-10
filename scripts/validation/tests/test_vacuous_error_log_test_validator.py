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

import contextlib
import importlib.util
import io
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
    # the soundness signal must be a QUERY, not prose
    # ------------------------------------------------------------------

    def test_prose_mentioning_taberror_log_does_not_exempt(self):
        """A docstring is not an assertion.

        Found by review with a working probe. The first version of
        `_queries_error_log` matched "Error Log" as a bare substring and the
        canonical vacuous test's own docstring exempted it; the fix hardened
        that branch and left `"tabError Log" in ...` beside it unchanged, so
        the identical bypass survived in the sibling branch. Both are pinned
        here now -- this test and the next.
        """
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def test_something_else_logs_a_thing(self):
                        \"\"\"This writes to tabError Log when it fails.\"\"\"
                        self.expectErrorLog("Some Title")
                        do_something()
                """
            ),
            ["test_something_else_logs_a_thing"],
        )

    def test_prose_mentioning_error_log_does_not_exempt(self):
        """Regression pin for the FIRST fix, not evidence for the second.

        Unlike the two tests either side of it, this one was already green
        against the pre-fix code -- the exact-match branch had been hardened
        earlier. It is here so that branch cannot quietly loosen again.
        """
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def test_rejection_logs_the_event(self):
                        \"\"\"A rejection writes a security Error Log.\"\"\"
                        self.expectErrorLog("Some Title")
                        do_something()
                """
            ),
            ["test_rejection_logs_the_event"],
        )

    def test_dead_string_assignment_does_not_exempt(self):
        """`x = "Error Log"` is not a query -- also found by review."""
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    def test_rejection_logs_the_event(self):
                        doctype = "Error Log"
                        self.expectErrorLog("Some Title")
                        do_something()
                """
            ),
            ["test_rejection_logs_the_event"],
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
    # prose inside a CALL is still prose -- review's six probes
    # ------------------------------------------------------------------

    def _vacuous_with(self, line: str) -> list:
        """A vacuous test whose only Error Log mention is `line`."""
        return self._names(
            f"""
            class T(EnhancedTestCase):
                def test_rejection_logs_the_event(self):
                    self.expectErrorLog("Some Title")
                    result = do_it()
                    {line}
            """
        )

    def test_literal_in_an_assertion_message_does_not_exempt(self):
        """The second bypass review found: position is not semantics.

        Requiring the literal to sit in CALL-ARGUMENT position stopped
        docstrings but accepted any call at all -- so an assertion message, a
        print(), a logging call or a decorator argument exempted a vacuous
        test just as well as a real query. "`tabError Log` is MyISAM
        (non-transactional)" is a recurring remark across 15+ test files here,
        so this was the prose an author was most likely to write.
        """
        for line in (
            'self.assertTrue(result, "expected write to tabError Log table")',
            'self.fail("no tabError Log row found")',
            'print("about to check tabError Log")',
            'logging.debug(f"tabError Log check for {result}")',
            'self.assertTrue(all(x for x in ["tabError Log", "y"]))',
        ):
            with self.subTest(line=line):
                self.assertEqual(
                    self._vacuous_with(line),
                    ["test_rejection_logs_the_event"],
                    f"prose in {line!r} must not count as asserting anything",
                )

    def test_literal_in_a_decorator_argument_does_not_exempt(self):
        self.assertEqual(
            self._names(
                """
                class T(EnhancedTestCase):
                    @unittest.skip("tabError Log check pending")
                    def test_rejection_logs_the_event(self):
                        self.expectErrorLog("Some Title")
                        do_it()
                """
            ),
            ["test_rejection_logs_the_event"],
        )

    def test_a_real_query_still_counts_as_sound(self):
        """The other direction: the tightening must not break real queries."""
        for line in (
            'self.assertTrue(frappe.db.exists("Error Log", {"error": ["like", "%x%"]}))',
            'self.assertTrue(frappe.get_all("Error Log", filters={"error": ["like", "%x%"]}))',
            'self.assertTrue(frappe.db.sql("SELECT name FROM `tabError Log`"))',
            'self.assertTrue(frappe.db.get_value("Error Log", {"error": "x"}, "name"))',
            'self.assertTrue(frappe.get_all(doctype="Error Log"))',
        ):
            with self.subTest(line=line):
                self.assertEqual(self._vacuous_with(line), [], f"{line!r} is a real query")

    def test_known_limit_doctype_hoisted_to_a_name(self):
        """A hoisted doctype constant is a FALSE POSITIVE. Pinned deliberately.

        `_queries_error_log` only sees literals at the query, so

            DOCTYPE = "Error Log"
            frappe.db.count(DOCTYPE, ...)

        is flagged even though the test genuinely queries the log. Measured on
        `fa440fcd6`: no test in the tree does this, so the live cost is zero
        and the remedy is a pragma. This test exists so that if anyone teaches
        the validator to resolve simple name bindings, they flip an assertion
        on purpose instead of discovering the change by accident.
        """
        self.assertEqual(
            self._names(
                """
                DOCTYPE = "Error Log"

                class T(EnhancedTestCase):
                    def test_rejection_logs_the_event(self):
                        self.expectErrorLog("Some Title")
                        before = frappe.db.count(DOCTYPE, {})
                        do_it()
                        self.assertGreater(frappe.db.count(DOCTYPE, {}), before)
                """
            ),
            ["test_rejection_logs_the_event"],
        )

    # ------------------------------------------------------------------
    # CLI modes
    # ------------------------------------------------------------------

    def test_stats_mode_reports_without_failing(self):
        path = self._write(
            """
            class T(EnhancedTestCase):
                def test_rejection_logs_the_event(self):
                    self.expectErrorLog("Sec")
                    do_it()
            """
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = v.main(["prog", "--stats", str(path)])
        self.assertEqual(rc, 0, "--stats must never gate")
        self.assertIn("test_rejection_logs_the_event", buf.getvalue())

    def test_audit_mode_uses_the_wide_pattern_and_does_not_latch_it(self):
        """--audit widens the pattern for ITS OWN run only.

        The pattern is threaded through as an argument; an earlier version
        assigned the module global, so one --audit run silently widened every
        later scan in the same process. The second half of this test is what
        pins that.
        """
        path = self._write(
            """
            class T(EnhancedTestCase):
                def test_failure_reports_partial_write(self):
                    self.expectErrorLog("Sec")
                    do_it()
            """
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = v.main(["prog", "--audit", str(path)])
        self.assertEqual(rc, 0, "--audit is a review aid, never a gate")
        self.assertIn("test_failure_reports_partial_write", buf.getvalue())

        # ...and the gate's own pattern is unchanged afterwards: a "reports"
        # name is not a log claim.
        self.assertEqual(self._names(path.read_text(encoding="utf-8")), [])

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
