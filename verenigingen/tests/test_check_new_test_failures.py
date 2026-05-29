"""Unit tests for the no-new-test-failures gate (scripts/testing/check_new_test_failures.py)."""

import importlib.util
import unittest
from pathlib import Path

# The checker lives in scripts/testing/ (not a Python package), so load it by path.
_CHECKER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "testing" / "check_new_test_failures.py"
)
_spec = importlib.util.spec_from_file_location("check_new_test_failures", _CHECKER_PATH)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


class TestExtractFailures(unittest.TestCase):
    def test_parses_ansi_wrapped_fail_lines(self):
        text = (
            "2026-05-29T00:00:00Z \x1b[41m FAIL \x1b[0m "
            "test_foo (verenigingen.tests.x.TestX.test_foo)\n"
            "2026-05-29T00:00:01Z \x1b[33m ERROR \x1b[0m "
            "test_bar (verenigingen.tests.y.TestY.test_bar)\n"
        )
        self.assertEqual(
            checker.extract_failures(text),
            {
                "test_foo (verenigingen.tests.x.TestX.test_foo)",
                "test_bar (verenigingen.tests.y.TestY.test_bar)",
            },
        )

    def test_parses_plain_colon_format(self):
        text = "FAIL: test_baz (verenigingen.tests.z.TestZ.test_baz)\n"
        self.assertEqual(
            checker.extract_failures(text),
            {"test_baz (verenigingen.tests.z.TestZ.test_baz)"},
        )

    def test_ignores_passing_and_noise_lines(self):
        text = (
            "   ✔  test_ok (verenigingen.tests.a.TestA.test_ok)\n"
            "Ran 3 tests in 1.2s\n"
            "Some FAILURE words in prose should not match a test id here\n"
        )
        self.assertEqual(checker.extract_failures(text), set())

    def test_does_not_match_fail_inside_traceback_message(self):
        # A traceback line mentioning "Error:" must not be mistaken for a result row.
        text = "AssertionError: create_customer_for_member failed for member X\n"
        self.assertEqual(checker.extract_failures(text), set())


class TestGateLogic(unittest.TestCase):
    def _write(self, tmp_path, name, content):
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.baseline = self._write(
            self.tmp,
            "baseline.txt",
            "# known failures\n"
            "test_old (verenigingen.tests.x.TestX.test_old)\n"
            "test_old2 (verenigingen.tests.x.TestX.test_old2)\n",
        )

    def test_clean_run_returns_zero(self):
        results = self._write(
            self.tmp, "r.txt", "FAIL test_old (verenigingen.tests.x.TestX.test_old)\n"
        )
        rc = checker.main(["--results", str(results), "--baseline", str(self.baseline)])
        self.assertEqual(rc, 0)

    def test_new_failure_returns_one(self):
        results = self._write(
            self.tmp,
            "r.txt",
            "FAIL test_old (verenigingen.tests.x.TestX.test_old)\n"
            "FAIL test_new (verenigingen.tests.x.TestX.test_new)\n",
        )
        rc = checker.main(["--results", str(results), "--baseline", str(self.baseline)])
        self.assertEqual(rc, 1)

    def test_missing_results_returns_two(self):
        rc = checker.main(
            ["--results", str(self.tmp / "nope.txt"), "--baseline", str(self.baseline)]
        )
        self.assertEqual(rc, 2)

    def test_truncated_or_empty_log_fails_completeness_guard(self):
        # An infra-killed shard's log (no test results at all) must NOT pass.
        results = self._write(self.tmp, "empty.txt", "<Error><Code>BlobNotFound</Code></Error>\n")
        rc = checker.main(["--results", str(results), "--baseline", str(self.baseline)])
        self.assertEqual(rc, 2)

    def test_ran_with_passes_but_no_failures_is_clean(self):
        # A shard that ran and only had baseline-known/zero failures should pass.
        results = self._write(
            self.tmp, "ok.txt", "   ✔  test_ok (verenigingen.tests.a.TestA.test_ok)\nRan 1 test\n"
        )
        rc = checker.main(["--results", str(results), "--baseline", str(self.baseline)])
        self.assertEqual(rc, 0)

    def test_emit_baseline_mode_does_not_gate(self):
        results = self._write(
            self.tmp, "r.txt", "FAIL test_new (verenigingen.tests.x.TestX.test_new)\n"
        )
        rc = checker.main(
            ["--results", str(results), "--baseline", str(self.baseline), "--emit-baseline"]
        )
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
