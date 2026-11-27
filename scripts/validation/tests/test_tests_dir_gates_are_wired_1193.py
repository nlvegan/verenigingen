#!/usr/bin/env python3
"""#1193: whole-tree AST gates that lived only under verenigingen/tests/ must be wired.

Two zero-tolerance gates ran only as one test among thousands in the sharded Tests job
(no pre-commit hook, no pre-push hook, no named CI job), the gap #1189 closed for #561:

* ``scripts/validation/db_clock_modified_write_validator.py`` (#453)
* ``scripts/validation/company_currency_scan_validator.py`` (#394)

This is a CI-config contract test: it reads ``.pre-commit-config.yaml`` and
``.github/workflows/code-validation.yml`` as TEXT (stdlib only, like the CI job that runs
it) and fails when a gate's script is missing, is not a pre-commit ``entry:``, or is not
run by a workflow step. It also runs each validator on a planted file, so a hook that
points at a script which exits 0 on everything cannot pass.

    python -m unittest discover -s scripts/validation/tests -p 'test_tests_dir_gates_are_wired_1193.py' -v
"""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PRE_COMMIT = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
WORKFLOW = (REPO / ".github" / "workflows" / "code-validation.yml").read_text(encoding="utf-8")

# script -> (a planted offending source, the bench test that imports the SAME scan)
GATES = {
    "scripts/validation/db_clock_modified_write_validator.py": (
        'q = "UPDATE `tabMember` SET modified = NOW() WHERE name = %s"\n',
        "verenigingen/tests/test_no_db_clock_modified_writes.py",
    ),
    "scripts/validation/company_currency_scan_validator.py": (
        'frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")\n',
        "verenigingen/tests/test_no_company_scan_by_currency.py",
    ),
}


def _pre_commit_entries():
    return re.findall(r"^\s*entry:\s*python\s+(\S+\.py)\b", PRE_COMMIT, re.MULTILINE)


def _hook_block(script):
    """The text of the pre-commit hook whose `entry:` runs ``script``."""
    for block in re.split(r"^\s*- id: ", PRE_COMMIT, flags=re.MULTILINE):
        if re.search(rf"entry:\s*python\s+{re.escape(script)}\b", block):
            return block
    return ""


def _hook_field(block, name):
    match = re.search(rf"^\s*{name}:\s*(.+)$", block, re.MULTILINE)
    return match.group(1).strip() if match else None


# A real path each scan covers, which the hook's `files:` regex must match.
COVERED_PATHS = {
    "scripts/validation/db_clock_modified_write_validator.py": ["verenigingen/services/x.py", "scripts/x.py"],
    "scripts/validation/company_currency_scan_validator.py": ["verenigingen/services/x.py"],
}


def _workflow_runs():
    return re.findall(r"^\s*run:\s*python\s+(\S+\.py)\b", WORKFLOW, re.MULTILINE)


class TestTestsDirGatesAreWired(unittest.TestCase):
    def test_each_gate_script_exists(self):
        for script in GATES:
            with self.subTest(script=script):
                self.assertTrue((REPO / script).is_file(), f"{script} is missing")

    def test_each_gate_is_a_precommit_hook(self):
        entries = _pre_commit_entries()
        for script in GATES:
            with self.subTest(script=script):
                self.assertIn(script, entries, f"no pre-commit `entry: python {script}`")

    def test_each_hook_is_live_and_selects_the_paths_its_scan_covers(self):
        for script, paths in COVERED_PATHS.items():
            with self.subTest(script=script):
                block = _hook_block(script)
                self.assertTrue(block, f"no hook block for {script}")
                stages = _hook_field(block, "stages") or "[pre-commit]"
                self.assertIn("pre-commit", stages)
                self.assertNotIn("manual", stages)
                pattern = (_hook_field(block, "files") or "").strip("'\"")
                exclude = (_hook_field(block, "exclude") or "").strip("'\"")
                self.assertTrue(pattern, "hook has no files: pattern")
                for path in paths:
                    self.assertTrue(re.search(pattern, path), f"files: {pattern!r} misses {path}")
                    if exclude:
                        self.assertFalse(re.search(exclude, path), f"exclude: {exclude!r} drops {path}")

    def test_each_gate_runs_in_a_named_ci_job(self):
        runs = _workflow_runs()
        for script in GATES:
            with self.subTest(script=script):
                self.assertIn(script, runs, f"code-validation.yml has no `run: python {script}`")

    def test_each_gate_has_its_own_unit_test_step(self):
        # The job must also run this contract so a rename of a script cannot go unnoticed.
        self.assertIn("test_tests_dir_gates_are_wired_1193.py", WORKFLOW)

    def test_the_bench_tests_import_the_same_scan(self):
        """No second, drifting copy: the bench test imports the standalone module."""
        for script, (_, bench_test) in GATES.items():
            module = script[: -len(".py")].replace("/", ".")
            with self.subTest(script=script):
                source = (REPO / bench_test).read_text(encoding="utf-8")
                self.assertIn(f"from {module} import", source)

    def test_each_gate_fails_on_a_planted_offender_and_passes_a_clean_file(self):
        for script, (offending, _) in GATES.items():
            with self.subTest(script=script), tempfile.TemporaryDirectory() as tmp:
                # The company scan only looks under verenigingen/, so plant it there.
                pkg = Path(tmp) / "verenigingen"
                pkg.mkdir()
                bad = pkg / "planted.py"
                bad.write_text(offending, encoding="utf-8")
                good = pkg / "clean.py"
                good.write_text("x = 1\n", encoding="utf-8")
                clean_root = tmp if "db_clock" in script else str(pkg)
                self.assertEqual(self._run_gate_cli(script, good, "--root", clean_root).returncode, 0)
                # The CLI itself, as pre-commit invokes it, must exit 1 on the offender.
                root = tmp if "db_clock" in script else str(pkg)
                result = self._run_gate_cli(script, bad, "--root", root)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("planted.py", result.stdout)
                self.assertTrue(self._planted_is_found(script, tmp))

    def _run_gate_cli(self, script, path, *extra):
        return subprocess.run(
            [sys.executable, "-I", str(REPO / script), str(path), *extra],
            capture_output=True,
            text=True,
            check=False,
        )

    def _planted_is_found(self, script, tmp):
        import importlib.util

        spec = importlib.util.spec_from_file_location(Path(script).stem, REPO / script)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        if "db_clock" in script:
            return bool(mod.scan_db_clock_modified_writes(root=tmp))
        return bool(mod.scan_company_currency_scans(root=str(Path(tmp) / "verenigingen")))


if __name__ == "__main__":
    unittest.main()
