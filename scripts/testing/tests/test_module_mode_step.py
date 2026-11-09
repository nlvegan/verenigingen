#!/usr/bin/env python3
"""Behaviour of the "Run selected test modules" step of _base-server-tests.yml (the PR-side
census job). The step's bash is lifted out of the workflow text and run against a FAKE
`bench` that prints canned unittest output, so what is judged is the real script, not a copy.

Stdlib only (no YAML parser): the step is cut out by its `- name:` markers.
"""

import os
import re
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

_WF = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "_base-server-tests.yml"
MOD = "verenigingen.tests.test_fake"


def step_script() -> str:
    text = _WF.read_text()
    start = text.index("- name: Run selected test modules")
    nxt = text.index("\n      - name:", start)
    body = text[start:nxt]
    run = body[body.index("run: |\n") + len("run: |\n"):]
    return textwrap.dedent(run).replace("${{ github.event.repository.name }}", "verenigingen")


class ModuleStep(unittest.TestCase):
    def run_step(self, bench_output: str, bench_rc: int = 0, modules: str = MOD, module_source: str = None):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "env" / "bin").mkdir(parents=True)
            if module_source is not None:
                src = ws / "apps" / "verenigingen" / (MOD.replace(".", "/") + ".py")
                src.parent.mkdir(parents=True)
                src.write_text(module_source)
            fake = ws / "fakebin"
            fake.mkdir()
            (fake / "bench").write_text(f"#!/bin/bash\ncat <<'EOT'\n{bench_output}\nEOT\nexit {bench_rc}\n")
            (fake / "bench").chmod((fake / "bench").stat().st_mode | stat.S_IXUSR)
            (ws / "env" / "bin" / "activate").write_text(f'export PATH="{fake}:$PATH"\n')
            (ws / "step.sh").write_text(step_script())
            res = subprocess.run(
                ["bash", "-e", str(ws / "step.sh")],
                env={**os.environ, "GITHUB_WORKSPACE": str(ws), "MODULES": modules},
                capture_output=True, text=True,
            )
            return res.returncode, res.stdout + res.stderr

    def test_ok_module_is_green(self):
        rc, out = self.run_step("Ran 18 tests in 1s\n\nOK")
        self.assertEqual(rc, 0, out)

    def test_a_module_with_one_skip_out_of_many_stays_green(self):
        # test_public_api_guest_access: 18 tests, 1 skipped.
        rc, out = self.run_step("Ran 18 tests in 15s\n\nOK (skipped=1)")
        self.assertEqual(rc, 0, out)

    def test_an_all_skipped_module_is_red_with_an_explicit_message(self):
        rc, out = self.run_step("Ran 2 tests in 0.1s\n\nOK (skipped=2)")
        self.assertEqual(rc, 1, out)
        self.assertIn("::error::", out)
        self.assertRegex(out, r"(?i)skipped")

    # #2364: a module that can never check anything in CI (live gateway credentials, a live
    # web server) declares it, and is then reported instead of failing the PR.
    MARKED = 'import unittest\n\nCI_ALWAYS_SKIPS = "needs Mollie test credentials"\n'

    def test_an_all_skipped_module_with_the_marker_is_green_with_a_warning(self):
        rc, out = self.run_step("Ran 2 tests in 0.1s\n\nOK (skipped=2)", module_source=self.MARKED)
        self.assertEqual(rc, 0, out)
        self.assertIn("::warning::", out)
        self.assertIn("needs Mollie test credentials", out)
        self.assertNotIn("::error::", out)

    def test_an_all_skipped_module_without_the_marker_stays_red(self):
        # Control: a source file exists, it just does not declare the marker.
        rc, out = self.run_step("Ran 2 tests in 0.1s\n\nOK (skipped=2)", module_source="import unittest\n")
        self.assertEqual(rc, 1, out)
        self.assertIn("::error::", out)

    def test_a_marker_with_an_empty_reason_does_not_count(self):
        rc, out = self.run_step(
            "Ran 2 tests in 0.1s\n\nOK (skipped=2)", module_source='CI_ALWAYS_SKIPS = ""\n'
        )
        self.assertEqual(rc, 1, out)

    def test_a_marker_mentioned_in_a_comment_does_not_count(self):
        rc, out = self.run_step(
            "Ran 2 tests in 0.1s\n\nOK (skipped=2)",
            module_source='# CI_ALWAYS_SKIPS = "not really"\nimport unittest\n',
        )
        self.assertEqual(rc, 1, out)

    def test_the_marker_does_not_rescue_a_module_that_collected_nothing(self):
        rc, out = self.run_step("Ran 0 tests in 0.0s\n\nOK", module_source=self.MARKED)
        self.assertEqual(rc, 1, out)

    def test_the_marker_does_not_rescue_a_failing_module(self):
        rc, out = self.run_step("Ran 2 tests\n\nFAILED (failures=1)", 1, module_source=self.MARKED)
        self.assertEqual(rc, 1, out)

    def test_a_module_that_ran_zero_tests_is_red(self):
        rc, out = self.run_step("Ran 0 tests in 0.0s\n\nOK")
        self.assertEqual(rc, 1, out)
        self.assertIn("::error::", out)

    def test_two_runs_in_one_output_are_summed(self):
        # test_site_timezone_naive_now prints two unittest summaries; 1 skip of 12 is fine.
        rc, out = self.run_step("Ran 8 tests in 9s\n\nOK\nRan 4 tests in 1s\n\nOK (skipped=1)")
        self.assertEqual(rc, 0, out)

    def test_failed_and_nonzero_exit_are_red(self):
        self.assertEqual(self.run_step("Ran 3 tests\n\nFAILED (failures=1)", 1)[0], 1)
        self.assertEqual(self.run_step("Ran 3 tests\n\nOK", 1)[0], 1)

    def test_no_output_at_all_is_red(self):
        self.assertEqual(self.run_step("")[0], 1)

    def test_an_empty_module_list_is_red(self):
        self.assertEqual(self.run_step("Ran 1 test\n\nOK", modules="")[0], 1)


if __name__ == "__main__":
    unittest.main()
