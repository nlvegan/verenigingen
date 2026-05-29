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

    def test_does_not_match_pip_error_prose(self):
        text = "ERROR: pip's dependency resolver does not currently take into account...\n"
        self.assertEqual(checker.extract_failures(text), set())

    def test_parses_fixture_hook_failures(self):
        # A setUpClass/setUpModule error fails a whole class/module — must be caught.
        text = (
            " ERROR  setUpClass (verenigingen.tests.x.TestX)\n"
            " ERROR  setUpModule (verenigingen.tests.y)\n"
        )
        self.assertEqual(
            checker.extract_failures(text),
            {
                "setUpClass (verenigingen.tests.x.TestX)",
                "setUpModule (verenigingen.tests.y)",
            },
        )


class TestGateLogic(unittest.TestCase):
    # Authoritative end-of-run sentinel the gate requires to trust a run as complete.
    SENTINEL = "Tests: 3, Failing: 1, Errors: 1\n"

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
            self.tmp,
            "r.txt",
            "FAIL test_old (verenigingen.tests.x.TestX.test_old)\n" + self.SENTINEL,
        )
        self.assertEqual(
            checker.main(["--results", str(results), "--baseline", str(self.baseline)]), 0
        )

    def test_new_failure_returns_one(self):
        results = self._write(
            self.tmp,
            "r.txt",
            "FAIL test_old (verenigingen.tests.x.TestX.test_old)\n"
            "FAIL test_new (verenigingen.tests.x.TestX.test_new)\n" + self.SENTINEL,
        )
        self.assertEqual(
            checker.main(["--results", str(results), "--baseline", str(self.baseline)]), 1
        )

    def test_missing_results_returns_two(self):
        rc = checker.main(
            ["--results", str(self.tmp / "nope.txt"), "--baseline", str(self.baseline)]
        )
        self.assertEqual(rc, 2)

    def test_empty_log_without_sentinel_fails(self):
        # An infra-killed shard's log (no results, no sentinel) must NOT pass.
        results = self._write(self.tmp, "empty.txt", "<Error><Code>BlobNotFound</Code></Error>\n")
        self.assertEqual(
            checker.main(["--results", str(results), "--baseline", str(self.baseline)]), 2
        )

    def test_crash_mid_run_with_streamed_failures_but_no_sentinel_fails(self):
        # THE critical hole: a shard that printed pass markers and a streamed "✖"
        # failure, then crashed before the summary/sentinel. The streamed "✖" line
        # carries no dotted path, so 0 failures are PARSED — but the run is NOT
        # complete, so the gate must fail (exit 2), not rubber-stamp a green check.
        results = self._write(
            self.tmp,
            "crash.txt",
            "   ✔  test_ok (verenigingen.tests.a.TestA.test_ok)\n"
            "   ✖  test_brand_new_regression\n"
            "Traceback (most recent call last): ... worker killed (OOM)\n",
        )
        self.assertEqual(
            checker.main(["--results", str(results), "--baseline", str(self.baseline)]), 2
        )

    def test_completed_run_with_only_baseline_failures_is_clean(self):
        results = self._write(
            self.tmp,
            "ok.txt",
            "   ✔  test_ok (verenigingen.tests.a.TestA.test_ok)\n"
            "FAIL test_old (verenigingen.tests.x.TestX.test_old)\n" + self.SENTINEL,
        )
        self.assertEqual(
            checker.main(["--results", str(results), "--baseline", str(self.baseline)]), 0
        )

    def test_new_fixture_hook_error_is_caught(self):
        results = self._write(
            self.tmp,
            "r.txt",
            " ERROR  setUpClass (verenigingen.tests.x.TestBrandNew)\n" + self.SENTINEL,
        )
        self.assertEqual(
            checker.main(["--results", str(results), "--baseline", str(self.baseline)]), 1
        )

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
