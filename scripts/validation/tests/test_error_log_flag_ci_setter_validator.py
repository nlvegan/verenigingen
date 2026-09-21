#!/usr/bin/env python3
"""Unit tests for scripts/validation/error_log_flag_ci_setter_validator.py.

Pure-Python (no bench/site needed): each case writes a small fixture file to a
temp dir and runs it through ``scan()``. Run with:
    python -m unittest discover -s scripts/validation/tests \
        -p 'test_error_log_flag_ci_setter_validator.py'

#1132's whole point is that a bare grep for ``VERENIGINGEN_FAIL_ON_ERROR_LOG``
is wrong from day one: this validator's own sibling
(``vacuous_error_log_test_validator.py``) names the variable in its docstring
without setting it, and would be a false positive for a naive grep. The
control tests below (``test_prose_mention_*``) are the load-bearing ones --
without them, this suite could not tell "detects settings" from "detects the
substring", which is precisely the failure mode #1132 was filed to prevent.
"""

import contextlib
import importlib.util
import io
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "error_log_flag_ci_setter_validator.py"
_spec = importlib.util.spec_from_file_location("error_log_flag_ci_setter_validator", _MOD_PATH)
v = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v
_spec.loader.exec_module(v)


class TestErrorLogFlagCiSetterValidator(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def _write(self, name: str, source: str) -> Path:
        path = Path(self._tmpdir.name) / name
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return path

    def _findings(self, path: Path):
        return v.scan([str(path)]).findings

    def _suppressed(self, path: Path):
        return v.scan([str(path)]).suppressed

    # -- real settings: YAML -------------------------------------------------

    def test_yaml_env_block_key_is_a_setting(self):
        path = self._write(
            "workflow.yml",
            """\
            jobs:
              audit:
                env:
                  VERENIGINGEN_FAIL_ON_ERROR_LOG: "1"
                steps:
                  - run: bench run-tests
            """,
        )
        findings = self._findings(path)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].file, str(path))

    def test_yaml_list_style_environment_entry_is_a_setting(self):
        path = self._write(
            "workflow.yml",
            """\
            environment:
              - VERENIGINGEN_FAIL_ON_ERROR_LOG=1
            """,
        )
        self.assertEqual(len(self._findings(path)), 1)

    # -- real settings: shell -------------------------------------------------

    def test_shell_export_is_a_setting(self):
        path = self._write(
            "wrapper.sh",
            """\
            #!/usr/bin/env bash
            export VERENIGINGEN_FAIL_ON_ERROR_LOG=1
            bench --site test_site_1 run-tests --app verenigingen
            """,
        )
        self.assertEqual(len(self._findings(path)), 1)

    def test_shell_inline_prefix_is_a_setting(self):
        path = self._write(
            "wrapper.sh",
            """\
            VERENIGINGEN_FAIL_ON_ERROR_LOG=1 bench --site test_site_1 run-tests --app verenigingen
            """,
        )
        self.assertEqual(len(self._findings(path)), 1)

    # -- real settings: python (AST) ------------------------------------------

    def test_python_os_environ_assignment_is_a_setting(self):
        path = self._write(
            "setter.py",
            """\
            import os

            os.environ["VERENIGINGEN_FAIL_ON_ERROR_LOG"] = "1"
            """,
        )
        self.assertEqual(len(self._findings(path)), 1)

    def test_python_os_environ_setdefault_is_a_setting(self):
        path = self._write(
            "setter.py",
            """\
            import os

            os.environ.setdefault("VERENIGINGEN_FAIL_ON_ERROR_LOG", "1")
            """,
        )
        self.assertEqual(len(self._findings(path)), 1)

    def test_python_subprocess_env_kwarg_dict_is_a_setting(self):
        path = self._write(
            "setter.py",
            """\
            import os
            import subprocess

            subprocess.run(
                ["bench", "run-tests"],
                env={**os.environ, "VERENIGINGEN_FAIL_ON_ERROR_LOG": "1"},
            )
            """,
        )
        self.assertEqual(len(self._findings(path)), 1)

    # -- the control: prose mentions must NOT trip the gate -------------------

    def test_prose_mention_in_python_docstring_is_not_a_setting(self):
        """The exact shape of the one real hit #1132 measured: a docstring
        bullet naming the variable with backticks, no assignment anywhere.
        This is the control -- without it, this validator is indistinguishable
        from a grep for the variable's name.
        """
        path = self._write(
            "validator_like.py",
            '''\
            """
            The automatic check only FAILS when ``VERENIGINGEN_FAIL_ON_ERROR_LOG``
            is truthy; otherwise it warns.
            """

            TARGET_VAR = "VERENIGINGEN_FAIL_ON_ERROR_LOG"


            def describe():
                """Mentions VERENIGINGEN_FAIL_ON_ERROR_LOG=1 as an example only."""
                return "set VERENIGINGEN_FAIL_ON_ERROR_LOG=1 to enable strict mode"
            ''',
        )
        self.assertEqual(self._findings(path), [])

    def test_the_real_sibling_docstring_is_not_a_setting(self):
        """Direct regression pin for the actual file #1132 named: scanning
        vacuous_error_log_test_validator.py itself must find zero settings,
        even though it names the variable in prose.
        """
        sibling = Path(__file__).resolve().parents[1] / "vacuous_error_log_test_validator.py"
        self.assertTrue(sibling.exists(), "sibling validator moved or renamed")
        self.assertEqual(self._findings(sibling), [])

    def test_yaml_comment_mentioning_the_var_is_not_a_setting(self):
        path = self._write(
            "workflow.yml",
            """\
            # Do not set VERENIGINGEN_FAIL_ON_ERROR_LOG=1 here, see #1118.
            jobs:
              audit:
                steps:
                  - run: bench run-tests
            """,
        )
        self.assertEqual(self._findings(path), [])

    def test_shell_comment_mentioning_the_var_is_not_a_setting(self):
        path = self._write(
            "wrapper.sh",
            """\
            # example only: VERENIGINGEN_FAIL_ON_ERROR_LOG=1
            bench run-tests
            """,
        )
        self.assertEqual(self._findings(path), [])

    def test_variable_name_mid_line_without_boundary_is_not_a_setting(self):
        """The anchor is at line start (after `- `/`export ` stripping) by
        design -- a mid-sentence YAML value is a documented NOT DETECTED case,
        not a bug. This test pins that boundary rather than leaving it
        implicit.
        """
        path = self._write(
            "workflow.yml",
            """\
            description: "run: VERENIGINGEN_FAIL_ON_ERROR_LOG=1 cmd"
            """,
        )
        self.assertEqual(self._findings(path), [])

    # -- pragma suppression: MUST be counted, never silently dropped -----------
    #
    # A rule with no baseline can only die through its escape hatch. Every test
    # in this block asserts BOTH halves: the line is no longer a finding, AND
    # it shows up in `suppressed` -- an untracked pragma on a zero-population
    # gate is indistinguishable from a hole with no record it was ever opened.

    def test_pragma_suppresses_a_real_setting_and_is_counted(self):
        path = self._write(
            "wrapper.sh",
            """\
            VERENIGINGEN_FAIL_ON_ERROR_LOG=1  # error-log-flag-setter-ok: runbook example
            """,
        )
        self.assertEqual(self._findings(path), [])
        suppressed = self._suppressed(path)
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(suppressed[0].reason, "runbook example")

    def test_python_pragma_suppresses_a_real_setting_and_is_counted(self):
        path = self._write(
            "setter.py",
            """\
            import os

            os.environ["VERENIGINGEN_FAIL_ON_ERROR_LOG"] = "1"  # error-log-flag-setter-ok: test fixture
            """,
        )
        self.assertEqual(self._findings(path), [])
        suppressed = self._suppressed(path)
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(suppressed[0].reason, "test fixture")

    def test_arbitrary_non_descriptive_reason_is_still_counted(self):
        """There is no restricted vocabulary here (unlike the sibling gates) --
        the reason string is free text. That must not mean an unhelpful reason
        makes the suppression itself invisible: it is still tracked, with
        whatever text the author wrote, verbatim.
        """
        path = self._write(
            "wrapper.sh",
            """\
            VERENIGINGEN_FAIL_ON_ERROR_LOG=1  # error-log-flag-setter-ok: anything at all, no review needed
            """,
        )
        self.assertEqual(self._findings(path), [])
        suppressed = self._suppressed(path)
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(suppressed[0].reason, "anything at all, no review needed")

    def test_suppressed_setting_is_discoverable_via_stats_output(self):
        """--stats is one of the two places a suppression must surface (the
        other is the plain whole-tree/batch run, covered below). Exercises the
        real CLI entry point, not just scan(), so a future refactor of main()
        cannot silently stop printing this.
        """
        path = self._write(
            "wrapper.sh",
            """\
            VERENIGINGEN_FAIL_ON_ERROR_LOG=1  # error-log-flag-setter-ok: anything at all, no review needed
            """,
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = v.main(["prog", str(path), "--stats"])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("suppressed via", output)
        self.assertIn("anything at all, no review needed", output)

    def test_suppressed_setting_is_discoverable_on_a_clean_exit_zero_run(self):
        """The stronger claim: even WITHOUT --stats, and even though the run
        exits 0 (no findings), the suppression is printed -- so it is visible
        by ordinary inspection of pre-commit/CI output, not only by someone
        remembering to pass --stats.
        """
        path = self._write(
            "wrapper.sh",
            """\
            VERENIGINGEN_FAIL_ON_ERROR_LOG=1  # error-log-flag-setter-ok: anything at all, no review needed
            """,
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = v.main(["prog", str(path)])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("suppressed", output)
        self.assertIn("anything at all, no review needed", output)

    # -- non-Python, non-text extensions are skipped ---------------------------

    def test_unrecognised_extension_is_not_scanned(self):
        path = self._write(
            "blob.json",
            """\
            {"VERENIGINGEN_FAIL_ON_ERROR_LOG": "1"}
            """,
        )
        self.assertEqual(self._findings(path), [])

    def test_the_validator_does_not_flag_itself(self):
        """The validator's own file is excluded from scanning; it is also,
        independently, clean by construction (see the two control tests
        above) -- this pins the explicit exclusion regardless.
        """
        result = v.scan([str(v._SELF_PATH)])
        self.assertEqual(result.findings, [])
        self.assertEqual(result.suppressed, [])


if __name__ == "__main__":
    unittest.main()
