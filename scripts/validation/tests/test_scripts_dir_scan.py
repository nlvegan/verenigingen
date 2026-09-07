#!/usr/bin/env python3
"""Unit tests for issue #1069: api_security_validator.py and insecure_api_detector.py
enumerate only `verenigingen/api/*.py` (recursively, since #972), so any whitelisted
endpoint defined under `scripts/` is invisible to a full-tree scan -- the only mode
the pre-push hooks actually run (both hooks call these scripts with no file_paths on
a full run: api-security-validator always via `pass_filenames: false`, and
insecure-api-detector's documented full-scan CLI mode shares the same code path).

`scripts/` is a real, importable top-level package (`scripts/__init__.py` exists) and
measured to hold 121 dispatch-reachable `frappe.whitelisted` endpoints -- none of them
have ever been scanned by either gate for a missing security decorator or an
unparameterised SQL string.

Pure-Python (no bench/site needed): builds a temp tree with BOTH a `verenigingen/api/`
file and a `scripts/` file, chdirs into its parent, and calls each validator's public
`validate_files()` / `scan_files()` entry point with no arguments (mirroring the
hooks' full-scan invocation). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_scripts_dir_scan.py
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SECURITY_DIR = Path(__file__).resolve().parents[1] / "security"


def _load(module_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(module_name, _SECURITY_DIR / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


api_security_validator = _load("api_security_validator_1069", "api_security_validator.py")
insecure_api_detector = _load("insecure_api_detector_1069", "insecure_api_detector.py")

API_ENDPOINT_SRC = (
    "import frappe\n\n"
    "@frappe.whitelist()\n"
    "def get_secret_from_api():\n"
    "    return frappe.db.sql('SELECT 1')\n"
)

# Deliberately undecorated (no security framework decorator) and using an
# unparameterised f-string in frappe.db.sql -- the exact planted-unguarded-
# endpoint shape the task asks for. Never committed for real; it only ever
# exists inside a throwaway temp directory for the duration of this test.
SCRIPTS_ENDPOINT_SRC = (
    "import frappe\n\n"
    "@frappe.whitelist()\n"
    "def get_secret_from_scripts(user_id):\n"
    "    return frappe.db.sql(f\"SELECT * FROM tabUser WHERE name = '{user_id}'\")\n"
)


class _ChdirToFakeAppTree(unittest.TestCase):
    """Builds <tmp>/verenigingen/api/top.py and <tmp>/scripts/nested/endpoint.py,
    then chdirs into <tmp> so a full scan with no file_paths mirrors the real
    pre-push hook invocation against a repo root."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_cwd = os.getcwd()
        root = Path(self._tmpdir.name)

        api_dir = root / "verenigingen" / "api"
        api_dir.mkdir(parents=True)
        (api_dir / "top_level.py").write_text(API_ENDPOINT_SRC)

        scripts_dir = root / "scripts" / "nested"
        scripts_dir.mkdir(parents=True)
        (root / "scripts" / "__init__.py").write_text("")
        (scripts_dir / "__init__.py").write_text("")
        (scripts_dir / "endpoint.py").write_text(SCRIPTS_ENDPOINT_SRC)

        os.chdir(root)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()


class ApiSecurityValidatorScriptsScanTest(_ChdirToFakeAppTree):
    def test_full_scan_finds_endpoint_under_scripts(self):
        validator = api_security_validator.APISecurityValidator(verbose=False)
        validator.validate_files(None)

        function_names = {p.function_name for p in validator.profiles}
        self.assertIn(
            "get_secret_from_scripts",
            function_names,
            "A full-tree scan (no file_paths given, exactly how the pre-push hook "
            "invokes this script) must find whitelisted functions defined under "
            f"scripts/, not just verenigingen/api/. Found only: {function_names}",
        )
        # Control: the verenigingen/api/ endpoint must still be found too.
        self.assertIn("get_secret_from_api", function_names)


class InsecureApiDetectorScriptsScanTest(_ChdirToFakeAppTree):
    def test_full_scan_finds_endpoint_under_scripts(self):
        detector = insecure_api_detector.InsecureAPIDetector(verbose=False)
        detector.scan_files(None)

        function_names = {e.function_name for e in detector.endpoints}
        self.assertIn(
            "get_secret_from_scripts",
            function_names,
            "A full-tree scan (no file_paths given, exactly how the pre-push hook "
            "invokes this script) must find whitelisted functions defined under "
            f"scripts/, not just verenigingen/api/. Found only: {function_names}",
        )
        # Control: the verenigingen/api/ endpoint must still be found too.
        self.assertIn("get_secret_from_api", function_names)


class _ChdirToEmptyTree(unittest.TestCase):
    """Builds an empty <tmp> with NEITHER verenigingen/api/ nor scripts/, and
    chdirs into it -- reproducing a misconfigured invocation (wrong cwd, a
    moved/renamed directory)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmpdir.name)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()


class ApiSecurityValidatorNoRootsFoundTest(_ChdirToEmptyTree):
    """#1078 review: a refactor accidentally made this fail OPEN (exit 0,
    "✅ All API endpoints pass") when neither scan root exists. A security
    gate reporting success after scanning nothing is the exact failure class
    (#1027/#1036's silent zero-count) this whole line of work exists to
    remove. This must never regress silently again."""

    def test_instance_flag_is_set_when_no_roots_exist(self):
        validator = api_security_validator.APISecurityValidator(verbose=False)
        result = validator.validate_files(None)

        self.assertTrue(
            validator.no_scan_roots_found,
            "validate_files() must record that it found no scan root at all, "
            "distinct from 'scanned everything and found zero issues'.",
        )
        self.assertFalse(result, "validate_files() must return False when nothing was scanned.")

    def test_cli_exits_non_zero_when_no_roots_exist(self):
        """The load-bearing case: the real subprocess exit code, exactly how
        the pre-push hook would observe it."""
        script = _SECURITY_DIR / "api_security_validator.py"
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=self._tmpdir.name,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(
            proc.returncode,
            0,
            "A run that finds no scan root must exit non-zero, not silently "
            f"report success. stdout was:\n{proc.stdout}",
        )


class InsecureApiDetectorNoRootsFoundTest(_ChdirToEmptyTree):
    def test_instance_flag_is_set_when_no_roots_exist(self):
        detector = insecure_api_detector.InsecureAPIDetector(verbose=False)
        result = detector.scan_files(None)

        self.assertTrue(
            detector.no_scan_roots_found,
            "scan_files() must record that it found no scan root at all, "
            "distinct from 'scanned everything and found zero issues'.",
        )
        self.assertFalse(result, "scan_files() must return False when nothing was scanned.")

    def test_cli_exits_non_zero_when_no_roots_exist(self):
        """The load-bearing case: the real subprocess exit code, exactly how
        the pre-push hook would observe it."""
        script = _SECURITY_DIR / "insecure_api_detector.py"
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=self._tmpdir.name,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(
            proc.returncode,
            0,
            "A run that finds no scan root must exit non-zero, not silently "
            f"report success. stdout was:\n{proc.stdout}",
        )


if __name__ == "__main__":
    unittest.main()
