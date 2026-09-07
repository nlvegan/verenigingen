#!/usr/bin/env python3
"""Unit tests for issue #1036: security_coverage_analyzer.py and
identify_high_risk_apis.py enumerate `verenigingen/api/*.py` with
`os.listdir(api_dir)` -- top-level only -- so any file under a subdirectory
of `verenigingen/api/` (e.g. the real `verenigingen/api/member/` package,
#972) is invisible to both scripts. `security_coverage_analyzer.py` also
hardcoded a non-existent `/home/frappe/...` path, so as shipped it never
even reached the listdir call with a real directory (#1027).

Pure-Python (imports frappe only to reach `frappe.get_app_path`, no
bench/site needed): builds a temp `api/{top_level.py, member/nested.py}`
tree and calls each script's real scanning code against it. Run with:
    python -m pytest scripts/security/tests/test_api_dir_recursive_scan.py -q
or plain:
    python scripts/security/tests/test_api_dir_recursive_scan.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

_SECURITY_DIR = Path(__file__).resolve().parents[1]


def _load(module_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(module_name, _SECURITY_DIR / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


security_coverage_analyzer = _load("security_coverage_analyzer_1036", "security_coverage_analyzer.py")
identify_high_risk_apis = _load("identify_high_risk_apis_1036", "identify_high_risk_apis.py")

TOP_LEVEL_SRC = "import frappe\n\n@frappe.whitelist()\ndef get_top_level():\n    return 1\n"
NESTED_SRC = "import frappe\n\n@frappe.whitelist()\ndef get_nested_secret():\n    return 1\n"


def _build_fake_api_tree(root: Path) -> Path:
    """Build <root>/api/{top_level.py, member/{__init__.py, nested.py}}."""
    api_dir = root / "api"
    sub_dir = api_dir / "member"
    sub_dir.mkdir(parents=True)

    (api_dir / "top_level.py").write_text(TOP_LEVEL_SRC)
    (sub_dir / "__init__.py").write_text("")
    (sub_dir / "nested.py").write_text(NESTED_SRC)
    return api_dir


class SecurityCoverageAnalyzerRecursionTest(unittest.TestCase):
    """find_unprotected_apis() resolves api_directory via frappe.get_app_path
    internally, so the fake app root is supplied by monkeypatching that."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        _build_fake_api_tree(root)

        patcher = patch.object(frappe, "get_app_path", return_value=str(root))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_find_unprotected_apis_finds_endpoint_in_subdirectory(self):
        unprotected = security_coverage_analyzer.find_unprotected_apis()

        found_functions = {
            fn["function_name"] for functions in unprotected.values() for fn in functions
        }
        self.assertIn(
            "get_nested_secret",
            found_functions,
            "find_unprotected_apis() must find unprotected @frappe.whitelist() "
            "functions defined under a subdirectory of verenigingen/api/ (e.g. "
            "api/member/), not just verenigingen/api/*.py directly -- "
            "os.listdir() alone silently misses them (#972/#1036). "
            f"Found only: {found_functions}",
        )
        # Control: the top-level file must still be found too.
        self.assertIn("get_top_level", found_functions)


class IdentifyHighRiskApisRecursionTest(unittest.TestCase):
    """_iter_api_python_files() takes api_dir as a parameter, so no
    frappe.get_app_path monkeypatch (or frappe bench context) is needed."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.api_dir = _build_fake_api_tree(Path(self._tmpdir.name))

    def test_iter_api_python_files_finds_file_in_subdirectory(self):
        found = {
            filename
            for filename, _file_path in identify_high_risk_apis._iter_api_python_files(
                str(self.api_dir)
            )
        }
        self.assertIn(
            str(Path("member") / "nested.py"),
            found,
            "The API-directory scan must walk into subdirectories of "
            "verenigingen/api/ (e.g. api/member/) -- os.listdir() alone "
            f"silently misses them (#972/#1036). Found only: {found}",
        )
        # Control: the top-level file must still be found too.
        self.assertIn("top_level.py", found)
        # Control: __init__.py must still be excluded, subdirectory or not.
        self.assertNotIn(str(Path("member") / "__init__.py"), found)


if __name__ == "__main__":
    unittest.main()
