#!/usr/bin/env python3
"""Unit tests for issue #1036: detailed_security_audit.py enumerates
`verenigingen/api/*.py` with `os.listdir(api_dir)` -- top-level only -- so
any file under a subdirectory of `verenigingen/api/` (e.g. the real
`verenigingen/api/member/` package, #972) is invisible to the audit. The
script also hardcoded a non-existent `/home/frappe/...` path, so as shipped
it never even reached the listdir call with a real directory (#1027).

Pure-Python, no frappe/bench context needed: `analyze_api_files()` takes
`api_dir` as a parameter, so this builds a temp
`api/{top_level.py, member/nested.py}` tree and passes it directly. Run
with:
    python -m pytest scripts/analysis/tests/test_api_dir_recursive_scan.py -q
or plain:
    python scripts/analysis/tests/test_api_dir_recursive_scan.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_ANALYSIS_DIR = Path(__file__).resolve().parents[1]


def _load(module_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(module_name, _ANALYSIS_DIR / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


detailed_security_audit = _load("detailed_security_audit_1036", "detailed_security_audit.py")

TOP_LEVEL_SRC = "import frappe\n\n@frappe.whitelist()\ndef get_top_level():\n    return 1\n"
NESTED_SRC = "import frappe\n\n@frappe.whitelist()\ndef get_nested_secret():\n    return 1\n"

HIGH_RISK_PATTERNS = [
    'payment', 'sepa', 'invoice', 'financial', 'donor', 'batch',
    'mandate', 'reconciliation', 'processing', 'termination',
]


class DetailedSecurityAuditRecursionTest(unittest.TestCase):
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
        self.api_dir = api_dir

    def test_analyze_api_files_finds_file_in_subdirectory(self):
        analysis = detailed_security_audit.analyze_api_files(str(self.api_dir), HIGH_RISK_PATTERNS)

        self.assertEqual(
            analysis["total_files"],
            2,
            "analyze_api_files() must count api/top_level.py AND "
            "api/member/nested.py -- os.listdir() alone silently misses "
            f"the subdirectory file (#972/#1036). Got: {analysis}",
        )
        scanned_names = set(analysis["security_details"].keys())
        self.assertIn(
            str(Path("member") / "nested.py"),
            scanned_names,
            "A file under a subdirectory of verenigingen/api/ (e.g. "
            "api/member/) must be scanned, not just verenigingen/api/*.py "
            f"directly (#972/#1036). Scanned: {scanned_names}",
        )
        # Control: the top-level file must still be found too.
        self.assertIn("top_level.py", scanned_names)


if __name__ == "__main__":
    unittest.main()
