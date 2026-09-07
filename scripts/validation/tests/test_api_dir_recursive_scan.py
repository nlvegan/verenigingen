#!/usr/bin/env python3
"""Unit tests for issue #972: api_security_validator.py and insecure_api_detector.py
enumerate `verenigingen/api/*.py` non-recursively, so any file under a subdirectory
of `verenigingen/api/` (e.g. the real `verenigingen/api/member/` package) is invisible
to a full-tree scan (the only mode the pre-push hooks actually run, since both hooks
call these scripts with `pass_filenames: false`).

Pure-Python (no bench/site needed): builds a temp `verenigingen/api/<subdir>/*.py`
tree, chdirs into its parent, and calls each validator's public `validate_files()` /
`scan_files()` entry point with no arguments (mirroring the hooks' full-scan
invocation). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_api_dir_recursive_scan.py
"""
import importlib.util
import os
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


api_security_validator = _load("api_security_validator_972", "api_security_validator.py")
insecure_api_detector = _load("insecure_api_detector_972", "insecure_api_detector.py")

UNDECORATED_ENDPOINT_SRC = (
    "import frappe\n\n"
    "@frappe.whitelist()\n"
    "def get_secret_from_subdir():\n"
    "    return frappe.db.sql('SELECT 1')\n"
)


class _ChdirToFakeApiTree(unittest.TestCase):
    """Builds <tmp>/verenigingen/api/{top.py, sub/nested.py} and chdirs into <tmp>."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_cwd = os.getcwd()
        root = Path(self._tmpdir.name)
        api_dir = root / "verenigingen" / "api"
        sub_dir = api_dir / "member"
        sub_dir.mkdir(parents=True)

        (api_dir / "top_level.py").write_text(UNDECORATED_ENDPOINT_SRC)
        (sub_dir / "__init__.py").write_text("")
        (sub_dir / "nested.py").write_text(
            UNDECORATED_ENDPOINT_SRC.replace(
                "get_secret_from_subdir", "get_secret_from_nested_subdir"
            )
        )

        os.chdir(root)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()


class ApiSecurityValidatorRecursionTest(_ChdirToFakeApiTree):
    def test_full_scan_finds_endpoint_in_api_subdirectory(self):
        validator = api_security_validator.APISecurityValidator(verbose=False)
        validator.validate_files(None)

        function_names = {p.function_name for p in validator.profiles}
        self.assertIn(
            "get_secret_from_nested_subdir",
            function_names,
            "A full-tree scan (no file_paths given, exactly how the pre-push hook "
            "invokes this script) must find whitelisted functions defined under a "
            "subdirectory of verenigingen/api/, not just verenigingen/api/*.py "
            f"directly. Found only: {function_names}",
        )
        # Control: the top-level file must still be found too.
        self.assertIn("get_secret_from_subdir", function_names)


class InsecureApiDetectorRecursionTest(_ChdirToFakeApiTree):
    def test_full_scan_finds_endpoint_in_api_subdirectory(self):
        detector = insecure_api_detector.InsecureAPIDetector(verbose=False)
        detector.scan_files(None)

        function_names = {e.function_name for e in detector.endpoints}
        self.assertIn(
            "get_secret_from_nested_subdir",
            function_names,
            "A full-tree scan (no file_paths given, exactly how the pre-push hook "
            "invokes this script) must find whitelisted functions defined under a "
            "subdirectory of verenigingen/api/, not just verenigingen/api/*.py "
            f"directly. Found only: {function_names}",
        )
        # Control: the top-level file must still be found too.
        self.assertIn("get_secret_from_subdir", function_names)


if __name__ == "__main__":
    unittest.main()
