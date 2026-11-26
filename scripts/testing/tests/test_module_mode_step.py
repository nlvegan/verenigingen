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
_CHECKER = Path(__file__).resolve().parents[1] / "check_ci_always_skips.py"


def step_script() -> str:
    text = _WF.read_text()
    start = text.index("- name: Run selected test modules")
    nxt = text.index("\n      - name:", start)
    body = text[start:nxt]
    run = body[body.index("run: |\n") + len("run: |\n"):]
    return textwrap.dedent(run).replace("${{ github.event.repository.name }}", "verenigingen")


class ModuleStep(unittest.TestCase):
    def run_step(self, bench_output: str, bench_rc: int = 0, modules: str = MOD, module_source=None):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            # The step asks the REAL checker about an all-skip module, which reads the module's
            # source under apps/<app>/ (#2364).
            app = ws / "apps" / "verenigingen"
            (app / "scripts" / "testing").mkdir(parents=True)
            (app / "scripts" / "testing" / "check_ci_always_skips.py").symlink_to(_CHECKER)
            (app / "verenigingen" / "tests").mkdir(parents=True)
            if module_source is not None:
                (app / "verenigingen" / "tests" / "test_fake.py").write_text(module_source)
            (ws / "env" / "bin").mkdir(parents=True)
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

    def test_an_all_skipped_module_declaring_ci_always_skips_is_green_and_names_the_reason(self):
        # #2364: a live-gateway module can never run in CI; its declared reason is logged.
        rc, out = self.run_step(
            "Ran 2 tests in 0.1s\n\nOK (skipped=2)",
            module_source='CI_ALWAYS_SKIPS = "needs live Mollie credentials"\n',
        )
        self.assertEqual(rc, 0, out)
        self.assertIn("::notice::", out)
        self.assertIn("needs live Mollie credentials", out)
        self.assertNotIn("::error::", out)

    def test_a_declared_always_skip_module_with_an_empty_reason_is_red(self):
        rc, out = self.run_step("Ran 2 tests in 0.1s\n\nOK (skipped=2)", module_source='CI_ALWAYS_SKIPS = ""\n')
        self.assertEqual(rc, 1, out)

    def test_the_marker_does_not_excuse_a_failure(self):
        src = 'CI_ALWAYS_SKIPS = "needs live Mollie credentials"\n'
        self.assertEqual(self.run_step("Ran 3 tests\n\nFAILED (failures=1)", 1, module_source=src)[0], 1)

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


class SeedStep(unittest.TestCase):
    """#2361: the runner prepares (runs `before_tests`) only for integration-category tests, so a
    module filed as "unspecified" runs on the fresh CI site with none of this app's seeds. The step
    seeds once, BEFORE the first module, and a failed seed fails the job without running modules."""

    SEED = "verenigingen.tests.setup.seed_for_standalone_module_runs"

    def run_step(self, seed_rc=0, modules=MOD):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "env" / "bin").mkdir(parents=True)
            fake = ws / "fakebin"
            fake.mkdir()
            calls = ws / "calls.log"
            # Logs every invocation; `execute` is the seed, anything else is a module run.
            (fake / "bench").write_text(
                f'#!/bin/bash\necho "$@" >> {calls}\n'
                f'if [[ " $* " == *" execute "* ]]; then echo "seeding"; exit {seed_rc}; fi\n'
                "printf 'Ran 3 tests in 1s\\n\\nOK\\n'\n"
            )
            (fake / "bench").chmod((fake / "bench").stat().st_mode | stat.S_IXUSR)
            (ws / "env" / "bin" / "activate").write_text(f'export PATH="{fake}:$PATH"\n')
            (ws / "step.sh").write_text(step_script())
            res = subprocess.run(
                ["bash", "-e", str(ws / "step.sh")],
                env={**os.environ, "GITHUB_WORKSPACE": str(ws), "MODULES": modules},
                capture_output=True, text=True,
            )
            lines = calls.read_text().splitlines() if calls.exists() else []
            return res.returncode, res.stdout + res.stderr, lines

    def test_the_seed_runs_once_on_the_test_site_before_the_first_module(self):
        rc, out, calls = self.run_step(modules=f"{MOD} {MOD}_b")
        self.assertEqual(rc, 0, out)
        seeds = [i for i, c in enumerate(calls) if " execute " in f" {c} "]
        self.assertEqual(len(seeds), 1, calls)
        self.assertEqual(seeds[0], 0, calls)
        self.assertEqual(calls[0], f"--site test_site execute {self.SEED}")
        self.assertEqual(len(calls), 3, calls)

    def test_a_failing_seed_fails_the_job_and_runs_no_module(self):
        rc, out, calls = self.run_step(seed_rc=1)
        self.assertNotEqual(rc, 0, out)
        self.assertEqual(len(calls), 1, calls)


if __name__ == "__main__":
    unittest.main()
