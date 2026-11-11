"""ci.yml's syntax/undefined-name gates must be able to fail (#2399).

``ci.yml`` runs on pull_request, merge_group and push, and its ``Code Quality`` job is a
REQUIRED context. Four steps swallowed their exit code, so a syntax error, an undefined name
or an invalid JSON file could never turn the check red:

* ``flake8 --select=E9,F63,F7,F82 ... || echo`` (Code Quality)
* ``python -m py_compile verenigingen/**/*.py || echo`` (Basic Validation); under ``sh`` the
  ``**`` is a plain ``*``, so only one directory level was ever compiled
* ``find -exec python -m json.tool {} \\; || echo``; ``find -exec ... \\;`` exits 0 whatever the
  command did, so the ``||`` was dead as well
* the "Import validation" ``ast.parse`` loop printed a cross and exited 0

Two kinds of check: a line-based shape scan (stdlib-only, no YAML parser, reusing the
siblings' scanner) and a behavioural run of the real step script against a scratch tree with
an injected defect, which is what proves the exit code and not just the text.
"""

import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from test_workflow_field_validator_exit_code import _SWALLOW, steps_running

_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"

# step name -> the command on that step which must be able to fail
_GATES = {
    "Run Flake8 linting": "flake8 .",
    "Syntax validation": "compileall",
    "Import validation": "ast.parse",
    "Check JavaScript/JSON files": "json.tool",
}


def _run_script(block: str) -> str:
    """The shell text of a step's ``run: |`` block, dedented."""
    lines = block.splitlines()
    start = next(i for i, ln in enumerate(lines) if re.match(r"^\s*run:\s*\|\s*$", ln))
    return textwrap.dedent("\n".join(lines[start + 1 :]))


class CiSyntaxGatesCanFailTests(unittest.TestCase):
    def setUp(self):
        self.text = _WORKFLOW.read_text()

    def _block(self, step_name):
        found = steps_running(self.text, "name: " + step_name)
        self.assertEqual(len(found), 1, (step_name, found))
        return found[0][1]

    def test_the_scan_finds_each_gate_with_its_command(self):
        # Control: a scan that finds nothing would pass the shape test below.
        for name, command in _GATES.items():
            with self.subTest(step=name):
                self.assertIn(command, self._block(name))

    def test_no_gate_command_line_swallows_the_exit_code(self):
        for name, command in _GATES.items():
            for line in self._block(name).splitlines():
                if command in line:
                    with self.subTest(step=name, line=line):
                        self.assertIsNone(_SWALLOW.search(line), line)

    def test_the_syntax_step_runs_under_a_posix_shell_without_globstar(self):
        # `verenigingen/**/*.py` is `verenigingen/*/*.py` without globstar: one level only.
        self.assertNotIn("**", _run_script(self._block("Syntax validation")))


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "needs bash and python3")
class CiSyntaxGatesExitCodeTests(unittest.TestCase):
    """Run the real step script (GitHub's default shell is ``bash -e``) in a scratch tree."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        deep = self.tmp / "verenigingen" / "a" / "b"
        deep.mkdir(parents=True)
        (self.tmp / "verenigingen" / "ok.py").write_text("x = 1\n")
        (deep / "ok.py").write_text("y = 2\n")
        (self.tmp / "data.json").write_text('{"a": 1}')
        self.text = _WORKFLOW.read_text()
        # `python` is what CI's setup-python provides; the dev box may only have python3.
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin" / "python").symlink_to(shutil.which("python3"))

    def _exit_code(self, step_name):
        (_, block), = steps_running(self.text, "name: " + step_name)
        script = _run_script(block)
        env = dict(os.environ, PATH="%s:%s" % (self.tmp / "bin", os.environ["PATH"]))
        return subprocess.run(
            ["bash", "-e", "-c", script], cwd=self.tmp, env=env, capture_output=True, text=True
        ).returncode

    def test_control_clean_tree_passes_every_step(self):
        for name in ("Syntax validation", "Import validation", "Check JavaScript/JSON files"):
            with self.subTest(step=name):
                self.assertEqual(self._exit_code(name), 0)

    def test_a_syntax_error_two_directories_deep_fails_the_syntax_step(self):
        (self.tmp / "verenigingen" / "a" / "b" / "bad.py").write_text("def f(:\n")
        self.assertNotEqual(self._exit_code("Syntax validation"), 0)

    def test_a_syntax_error_fails_the_import_validation_step(self):
        (self.tmp / "verenigingen" / "a" / "b" / "bad.py").write_text("def f(:\n")
        self.assertNotEqual(self._exit_code("Import validation"), 0)

    def test_invalid_json_fails_the_json_step(self):
        (self.tmp / "verenigingen" / "a").joinpath("bad.json").write_text("{not json")
        self.assertNotEqual(self._exit_code("Check JavaScript/JSON files"), 0)

    @unittest.skipUnless(shutil.which("flake8"), "flake8 not installed")
    def test_a_flake8_finding_fails_the_flake8_step(self):
        # E9 (syntax). F821 cannot be used here: the repo's `.flake8` ignores it, so the
        # F82 in the select set never reports an undefined name (filed separately).
        (self.tmp / "verenigingen" / "bad.py").write_text("def f(:\n")
        self.assertNotEqual(self._exit_code("Run Flake8 linting"), 0)


if __name__ == "__main__":
    unittest.main()
