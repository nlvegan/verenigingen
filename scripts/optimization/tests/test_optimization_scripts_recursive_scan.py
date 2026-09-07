#!/usr/bin/env python3
"""Unit tests for issue #1036: preview_optimizations.py and
analyze_api_optimization_status.py enumerate `verenigingen/api/*.py`
non-recursively (`api_dir.glob("*.py")`), so any file under a subdirectory of
`verenigingen/api/` (e.g. the real `verenigingen/api/member/` package, #972)
is invisible to both scripts. Both also hardcoded a non-existent
`/home/frappe/...` path, so as shipped they crashed (ZeroDivisionError /
IncorrectSitePath-style breakage) before the glob ever mattered (#1027).

Pure-Python (imports frappe only to monkeypatch `frappe.get_app_path`, no
bench/site needed): builds a temp `api/{top_level.py, member/nested.py}`
tree, points `frappe.get_app_path("verenigingen")` at it, and calls each
script's real scanning entry point. Run with:
    python -m pytest scripts/optimization/tests/test_api_dir_recursive_scan.py -q
or plain:
    python scripts/optimization/tests/test_api_dir_recursive_scan.py
"""
import contextlib
import importlib.util
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

_OPTIMIZATION_DIR = Path(__file__).resolve().parents[1]


def _load(module_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(module_name, _OPTIMIZATION_DIR / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


preview_optimizations = _load("preview_optimizations_1036", "preview_optimizations.py")
analyze_api_optimization_status = _load(
    "analyze_api_optimization_status_1036", "analyze_api_optimization_status.py"
)

TOP_LEVEL_SRC = "import frappe\n\n@frappe.whitelist()\ndef get_top_level():\n    return 1\n"
NESTED_SRC = "import frappe\n\n@frappe.whitelist()\ndef get_nested_secret():\n    return 1\n"


class _FakeApiTree(unittest.TestCase):
    """Builds <tmp>/api/{top_level.py, member/nested.py} and points
    frappe.get_app_path("verenigingen") at <tmp> for the duration of the test."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        api_dir = root / "api"
        sub_dir = api_dir / "member"
        sub_dir.mkdir(parents=True)

        (api_dir / "top_level.py").write_text(TOP_LEVEL_SRC)
        (sub_dir / "__init__.py").write_text("")
        (sub_dir / "nested.py").write_text(NESTED_SRC)

        patcher = patch.object(frappe, "get_app_path", return_value=str(root))
        patcher.start()
        self.addCleanup(patcher.stop)


class PreviewOptimizationsRecursionTest(_FakeApiTree):
    def test_check_existing_optimizations_counts_nested_endpoint(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            preview_optimizations.check_existing_optimizations()

        match = re.search(r"Total API endpoints: (\d+)", buf.getvalue())
        self.assertIsNotNone(match, buf.getvalue())
        self.assertEqual(
            int(match.group(1)),
            2,
            "A full scan must count @frappe.whitelist endpoints in both "
            "api/top_level.py and api/member/nested.py -- a non-recursive "
            "glob('*.py') silently misses the subdirectory file (#972/#1036). "
            f"Full output:\n{buf.getvalue()}",
        )


class AnalyzeApiOptimizationStatusRecursionTest(_FakeApiTree):
    def test_analyze_api_files_counts_nested_endpoint(self):
        results = analyze_api_optimization_status.analyze_api_files()

        self.assertEqual(
            results["total_endpoints"],
            2,
            "A full scan must count @frappe.whitelist endpoints in both "
            "api/top_level.py and api/member/nested.py -- a non-recursive "
            "glob('*.py') silently misses the subdirectory file (#972/#1036). "
            f"Got: {results}",
        )


if __name__ == "__main__":
    unittest.main()
