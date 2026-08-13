#!/usr/bin/env python3
"""Unit tests for scripts/testing/check_test_leaks.py.

Pure-Python (no bench/site needed): the gate reads a text log and a baseline file.

The log fixtures below are BYTE-FAITHFUL to what `bench run-parallel-tests` actually
emits -- captured from a real run (a Territory whose child was created with capture
suspended, so the drain cannot delete the parent). The leak line arrives indented and
prefixed with frappe's `U+25B9` stdout marker, NOT at column 0, and the class header
that tells us which module ran is a bare dotted path on its own line. A parser written
against an imagined format passes its own tests and reads zero leaks in CI.

Run with:  python -m pytest this_file.py
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "check_test_leaks.py"
_spec = importlib.util.spec_from_file_location("check_test_leaks", _MOD_PATH)
ctl = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ctl
_spec.loader.exec_module(ctl)


LEAK_LINE = (
    "       ▹  TEST-LEAK verenigingen.tests.test_a.ClassA.test_one "
    "Territory::zzprobe-parent-10125d Cannot delete zzprobe-parent-10125d as it has child nodes"
)
SENTINEL = "Tests: 42, Failing: 0, Errors: 0"


def _log(*lines):
    return "\n".join(lines) + "\n"


class ExtractLeaksTest(unittest.TestCase):
    def test_it_reads_the_real_indented_marker_line(self):
        leaks = ctl.extract_leaks(_log(LEAK_LINE))
        self.assertEqual(1, len(leaks))
        self.assertEqual("verenigingen.tests.test_a.ClassA.test_one", leaks[0].test_id)

    def test_the_module_drops_the_class_and_method(self):
        leaks = ctl.extract_leaks(_log(LEAK_LINE))
        self.assertEqual("verenigingen.tests.test_a", leaks[0].module)

    def test_it_keeps_the_record_identity_for_triage(self):
        leaks = ctl.extract_leaks(_log(LEAK_LINE))
        self.assertIn("Territory::zzprobe-parent-10125d", leaks[0].detail)

    def test_ansi_colour_codes_do_not_hide_a_leak(self):
        coloured = "   \x1b[33m ▹ \x1b[0m " + LEAK_LINE.split("▹  ")[1]
        self.assertEqual(1, len(ctl.extract_leaks(_log(coloured))))

    def test_a_doctype_with_spaces_survives_parsing(self):
        line = (
            "  ▹  TEST-LEAK verenigingen.tests.test_b.ClassB.test_x "
            "Sales Invoice::ACC-SINV-2026-00042 Cannot delete: linked with Payment Entry"
        )
        leaks = ctl.extract_leaks(_log(line))
        self.assertEqual("verenigingen.tests.test_b", leaks[0].module)
        self.assertIn("Sales Invoice::ACC-SINV-2026-00042", leaks[0].detail)

    def test_a_log_with_no_leaks_yields_none(self):
        self.assertEqual([], ctl.extract_leaks(_log("   ✔  test_something", SENTINEL)))

    def test_the_word_in_prose_is_not_a_leak(self):
        prose = "the ratchet greps for TEST-LEAK lines in the shard log"
        self.assertEqual([], ctl.extract_leaks(_log(prose)))

    def test_a_truncated_leak_line_is_still_counted(self):
        """CI truncates long lines. A leak we cannot fully identify is still a leak.

        Requiring `Doctype::name` to match would drop it -- under-counting in exactly
        the case where the evidence is already thin.
        """
        truncated = "  ▹  TEST-LEAK verenigingen.tests.test_a.ClassA.test_one Sales Inv"
        leaks = ctl.extract_leaks(_log(truncated))
        self.assertEqual(1, len(leaks))
        self.assertEqual("verenigingen.tests.test_a", leaks[0].module)

    def test_the_same_record_reported_twice_counts_once(self):
        """Under VERENIGINGEN_FAIL_ON_TEST_LEAK the line is printed AND echoed in the
        AssertionError, so the same record appears twice in one log."""
        echoed = "    " + LEAK_LINE.split("▹  ")[1]
        leaks = ctl.extract_leaks(_log(LEAK_LINE, echoed))
        self.assertEqual(1, len(leaks))


class CountByModuleTest(unittest.TestCase):
    def test_two_leaks_in_one_module_count_as_two(self):
        second = LEAK_LINE.replace("test_one", "test_two").replace("10125d", "aa77bc")
        counts = ctl.count_by_module(ctl.extract_leaks(_log(LEAK_LINE, second)))
        self.assertEqual({"verenigingen.tests.test_a": 2}, counts)


class ModulesThatRanTest(unittest.TestCase):
    """Scope. A shard log covers ~110 of 1315 modules; the rest simply did not run."""

    def test_a_class_header_marks_its_module_as_run(self):
        ran = ctl.modules_that_ran(_log("verenigingen.tests.test_a.ClassA", SENTINEL))
        self.assertIn("verenigingen.tests.test_a", ran)

    def test_a_module_absent_from_the_log_did_not_run(self):
        ran = ctl.modules_that_ran(_log("verenigingen.tests.test_a.ClassA", SENTINEL))
        self.assertNotIn("verenigingen.tests.test_zzz", ran)

    def test_indented_result_lines_are_not_class_headers(self):
        ran = ctl.modules_that_ran(_log("   ✔  test_something — ok", SENTINEL))
        self.assertEqual(set(), ran)


class RunCompletedTest(unittest.TestCase):
    def test_the_sentinel_marks_a_finished_run(self):
        self.assertTrue(ctl.run_completed(_log(SENTINEL)))

    def test_a_truncated_log_is_not_a_finished_run(self):
        self.assertFalse(ctl.run_completed(_log("verenigingen.tests.test_a.ClassA")))


class GateTest(unittest.TestCase):
    """End-to-end through main(): the exit code is the contract CI reads."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def _write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def _run(self, log_text, baseline_text, *extra):
        return ctl.main(
            [
                "--results",
                self._write("run.log", log_text),
                "--baseline",
                self._write("baseline.txt", baseline_text),
                *extra,
            ]
        )

    def test_a_run_that_did_not_finish_is_inconclusive_not_clean(self):
        """The failure mode this gate exists to avoid: a killed shard reading as zero."""
        rc = self._run(_log("verenigingen.tests.test_a.ClassA"), "verenigingen.tests.test_a 0\n")
        self.assertEqual(2, rc)

    def test_a_leak_above_baseline_fails(self):
        rc = self._run(
            _log("verenigingen.tests.test_a.ClassA", LEAK_LINE, SENTINEL),
            "verenigingen.tests.test_a 0\n",
        )
        self.assertEqual(1, rc)

    def test_a_leak_at_baseline_passes(self):
        rc = self._run(
            _log("verenigingen.tests.test_a.ClassA", LEAK_LINE, SENTINEL),
            "verenigingen.tests.test_a 1\n",
        )
        self.assertEqual(0, rc)

    def test_a_module_that_leaks_for_the_first_time_fails(self):
        rc = self._run(
            _log("verenigingen.tests.test_a.ClassA", LEAK_LINE, SENTINEL),
            "# nothing baselined yet\n",
        )
        self.assertEqual(1, rc)

    def test_fewer_leaks_than_baseline_passes(self):
        rc = self._run(
            _log("verenigingen.tests.test_a.ClassA", SENTINEL),
            "verenigingen.tests.test_a 3\n",
        )
        self.assertEqual(0, rc)

    def test_a_baselined_module_that_did_not_run_is_not_an_improvement(self):
        """Only modules this shard actually ran may move the ratchet.

        Otherwise every shard would report the other eleven shards' modules as
        fixed, and --update would erase a debt nobody paid.
        """
        log = _log("verenigingen.tests.test_a.ClassA", SENTINEL)
        baseline = "verenigingen.tests.test_a 0\nverenigingen.tests.test_elsewhere 5\n"
        rc = ctl.main(
            [
                "--results",
                self._write("run.log", log),
                "--baseline",
                self._write("baseline.txt", baseline),
                "--update",
            ]
        )
        self.assertEqual(0, rc)
        updated = (self.dir / "baseline.txt").read_text(encoding="utf-8")
        self.assertIn("verenigingen.tests.test_elsewhere 5", updated)

    def test_update_ratchets_a_module_down_to_what_it_now_leaks(self):
        log = _log("verenigingen.tests.test_a.ClassA", LEAK_LINE, SENTINEL)
        rc = ctl.main(
            [
                "--results",
                self._write("run.log", log),
                "--baseline",
                self._write("baseline.txt", "verenigingen.tests.test_a 4\n"),
                "--update",
            ]
        )
        self.assertEqual(0, rc)
        updated = (self.dir / "baseline.txt").read_text(encoding="utf-8")
        self.assertIn("verenigingen.tests.test_a 1", updated)
        self.assertNotIn("verenigingen.tests.test_a 4", updated)

    def test_update_never_raises_a_baseline(self):
        """--update is a ratchet, not a rubber stamp: it must not absorb a regression."""
        log = _log("verenigingen.tests.test_a.ClassA", LEAK_LINE, SENTINEL)
        rc = ctl.main(
            [
                "--results",
                self._write("run.log", log),
                "--baseline",
                self._write("baseline.txt", "verenigingen.tests.test_a 0\n"),
                "--update",
            ]
        )
        self.assertEqual(1, rc)
        updated = (self.dir / "baseline.txt").read_text(encoding="utf-8")
        self.assertIn("verenigingen.tests.test_a 0", updated)

    def test_emit_baseline_prints_the_observed_counts(self):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = ctl.main(
                [
                    "--results",
                    self._write("run.log", _log("verenigingen.tests.test_a.ClassA", LEAK_LINE, SENTINEL)),
                    "--emit-baseline",
                ]
            )
        self.assertEqual(0, rc)
        self.assertIn("verenigingen.tests.test_a 1", buf.getvalue())

    def test_a_missing_results_file_is_a_usage_error(self):
        rc = ctl.main(["--results", str(self.dir / "nope.log"), "--baseline", self._write("b.txt", "")])
        self.assertEqual(2, rc)


if __name__ == "__main__":
    unittest.main()
