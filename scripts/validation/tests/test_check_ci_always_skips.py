#!/usr/bin/env python3
"""Unit tests for scripts/testing/check_ci_always_skips.py (#2364): the decision "is this module's
all-skip result acceptable in the PR census job?".

A module may declare `CI_ALWAYS_SKIPS = "<reason>"` at module level (a live-gateway test CI can
never run). Only then is an all-skip run accepted; every other all-skip module stays red.
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "testing" / "check_ci_always_skips.py"
_spec = importlib.util.spec_from_file_location("check_ci_always_skips", _PATH)
cas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cas)

MARKED = 'CI_ALWAYS_SKIPS = "needs live Mollie credentials"\n\nclass T:\n    pass\n'
UNMARKED = "import unittest\n\nclass T(unittest.TestCase):\n    pass\n"
EMPTY = 'CI_ALWAYS_SKIPS = ""\n'
BLANK = 'CI_ALWAYS_SKIPS = "   "\n'
NOT_A_STRING = "CI_ALWAYS_SKIPS = True\n"
NESTED = 'class T:\n    CI_ALWAYS_SKIPS = "inside a class does not count"\n'
IN_FUNCTION = 'def f():\n    CI_ALWAYS_SKIPS = "inside a function does not count"\n'
MOD = "verenigingen.tests.test_fake"


class Decide(unittest.TestCase):
    def test_marked_all_skip_module_is_accepted_and_the_reason_is_logged(self):
        ok, lines = cas.decide(MARKED, MOD, ran=2, skipped=2)
        self.assertTrue(ok)
        self.assertTrue(any(ln.startswith("::notice::") and "needs live Mollie credentials" in ln for ln in lines), lines)

    def test_marked_module_that_ran_zero_tests_is_accepted(self):
        # a setUpClass skip prints "Ran 0 tests / OK (skipped=1)"
        self.assertTrue(cas.decide(MARKED, MOD, ran=0, skipped=1)[0])

    def test_unmarked_all_skip_module_is_refused(self):
        ok, lines = cas.decide(UNMARKED, MOD, ran=4, skipped=4)
        self.assertFalse(ok)
        self.assertTrue(any(ln.startswith("::error::") and "checked nothing: ran 4 test(s), 4 skipped" in ln for ln in lines), lines)

    def test_unmarked_module_that_ran_zero_tests_is_refused(self):
        self.assertFalse(cas.decide(UNMARKED, MOD, ran=0, skipped=0)[0])

    def test_module_that_ran_tests_is_fine_marked_or_not(self):
        self.assertTrue(cas.decide(UNMARKED, MOD, ran=18, skipped=1)[0])
        ok, lines = cas.decide(MARKED, MOD, ran=18, skipped=1)
        self.assertTrue(ok)
        # a marked module that now really runs is worth a nudge, never a failure
        self.assertFalse(any(ln.startswith("::error::") for ln in lines), lines)

    def test_empty_or_blank_or_non_string_reason_is_refused(self):
        for src in (EMPTY, BLANK, NOT_A_STRING):
            with self.subTest(src=src):
                ok, lines = cas.decide(src, MOD, ran=2, skipped=2)
                self.assertFalse(ok)
                self.assertTrue(any(ln.startswith("::error::") for ln in lines), lines)

    def test_marker_must_be_module_level(self):
        for src in (NESTED, IN_FUNCTION):
            with self.subTest(src=src):
                self.assertFalse(cas.decide(src, MOD, ran=2, skipped=2)[0])

    def test_syntax_error_source_is_refused(self):
        self.assertFalse(cas.decide("def (:\n", MOD, ran=2, skipped=2)[0])


class Cli(unittest.TestCase):
    def run_cli(self, source, ran, skipped):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "verenigingen" / "tests"
            p.mkdir(parents=True)
            if source is not None:
                (p / "test_fake.py").write_text(source)
            res = subprocess.run(
                [sys.executable, str(_PATH), "--module", MOD, "--ran", str(ran), "--skipped", str(skipped),
                 "--app-root", d],
                capture_output=True, text=True,
            )
            return res.returncode, res.stdout

    def test_cli_reads_the_module_file(self):
        self.assertEqual(self.run_cli(MARKED, 2, 2)[0], 0)
        self.assertEqual(self.run_cli(UNMARKED, 2, 2)[0], 1)

    def test_cli_refuses_when_the_module_file_is_missing(self):
        self.assertEqual(self.run_cli(None, 2, 2)[0], 1)


if __name__ == "__main__":
    unittest.main()
