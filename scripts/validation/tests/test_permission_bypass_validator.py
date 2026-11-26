#!/usr/bin/env python3
"""Unit tests for issue #1076: permission_bypass_validator.py's `get_all_python_files()`
(the `--all` full-scan entry point) hardcoded a single `base_path='verenigingen'`
default, so `scripts/` -- a real importable package with permission-bypass usages
of its own -- was never covered by a full scan. Same class as #1069's fix to the
sibling API security validators.

Pure-Python (no bench/site needed). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_permission_bypass_validator.py
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "security" / "permission_bypass_validator.py"
_spec = importlib.util.spec_from_file_location("permission_bypass_validator_1076", _SCRIPT)
pbv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pbv
_spec.loader.exec_module(pbv)


class GetAllPythonFilesTest(unittest.TestCase):
    def _tree(self, d):
        root = Path(d)
        (root / "verenigingen").mkdir()
        (root / "scripts").mkdir()
        (root / "verenigingen" / "a.py").write_text("x = 1\n")
        (root / "scripts" / "b.py").write_text("y = 2\n")
        return root

    def test_default_scans_both_roots(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(d)
            import os

            old_cwd = os.getcwd()
            os.chdir(root)
            try:
                files = pbv.get_all_python_files()
            finally:
                os.chdir(old_cwd)
            rels = {str(Path(f)) for f in files}
            self.assertIn(str(Path("verenigingen/a.py")), rels)
            self.assertIn(
                str(Path("scripts/b.py")),
                rels,
                "the default scan must cover scripts/ too, not just verenigingen/",
            )

    def test_a_single_string_argument_still_works(self):
        """Backward compatibility: any external caller passing the old
        single-root positional string must keep working exactly as before."""
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(d)
            import os

            old_cwd = os.getcwd()
            os.chdir(root)
            try:
                files = pbv.get_all_python_files("verenigingen")
            finally:
                os.chdir(old_cwd)
            rels = {str(Path(f)) for f in files}
            self.assertIn(str(Path("verenigingen/a.py")), rels)
            self.assertNotIn(str(Path("scripts/b.py")), rels)


class NoScanRootsFoundTest(unittest.TestCase):
    """#1078's fail-open regression, applied here: `--all` finding NEITHER
    scan root must hard-fail, not silently report the same "0 issues" success
    a genuinely clean full scan would."""

    def test_all_flag_exits_non_zero_when_neither_root_exists(self):
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run(
                [sys.executable, str(_SCRIPT), "--all"],
                cwd=d,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(
                0,
                proc.returncode,
                f"a run that finds no scan root must exit non-zero. "
                f"Output:\n{proc.stdout}{proc.stderr}",
            )


class JustificationWindowAndVariablePassthroughTest(unittest.TestCase):
    """#971: (B) a justification 7 lines above a bypass counted as absent (window
    of 5); (A) `save(ignore_permissions=<variable>)` was never detected."""

    def _scan(self, source):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "services" / "svc971.py"
            path.parent.mkdir()
            path.write_text(source)
            return pbv.find_permission_bypasses(str(path))

    def test_justification_seven_lines_above_counts(self):
        src = "# Security: reviewed, caller is trusted\n" + "x = 1\n" * 6 + "doc.flags.ignore_permissions = True\n"
        (finding,) = self._scan(src)
        self.assertEqual(8, finding.line_number)
        self.assertTrue(finding.has_justification)

    def test_justification_far_outside_window_does_not_count(self):
        gap = 12  # clearly beyond the 10-line window; docstring scan is not involved
        src = "# Security: reviewed\n" + "x = 1\n" * gap + "doc.save(ignore_permissions=True)\n"
        (finding,) = self._scan(src)
        self.assertFalse(finding.has_justification)

    def test_justification_exactly_ten_lines_above_counts(self):
        src = "# Security: reviewed\n" + "x = 1\n" * 9 + "doc.save(ignore_permissions=True)\n"
        (finding,) = self._scan(src)
        self.assertEqual(11, finding.line_number)  # comment on line 1 = 10 lines above
        self.assertTrue(finding.has_justification)

    def test_justification_eleven_lines_above_does_not_count(self):
        src = "# Security: reviewed\n" + "x = 1\n" * 10 + "doc.save(ignore_permissions=True)\n"
        (finding,) = self._scan(src)
        self.assertEqual(12, finding.line_number)  # comment on line 1 = 11 lines above
        self.assertFalse(finding.has_justification)

    def test_literal_true_without_justification_still_flagged(self):
        (finding,) = self._scan("doc.save(ignore_permissions=True)\n")
        self.assertFalse(finding.has_justification)
        self.assertEqual(pbv.RiskLevel.HIGH, finding.risk_level)

    def test_variable_passthrough_is_detected(self):
        (finding,) = self._scan("def f(ignore_permissions=False):\n    doc.save(ignore_permissions=ignore_permissions)\n")
        self.assertEqual(2, finding.line_number)
        self.assertFalse(finding.has_justification)

    def test_call_result_passthrough_is_detected_and_can_be_justified(self):
        src = "# Security: True only inside an authorised follow-on\ndoc.insert(ignore_permissions=helper())\n"
        (finding,) = self._scan(src)
        self.assertTrue(finding.has_justification)

    def test_multiline_call_reports_the_keyword_line(self):
        (finding,) = self._scan("doc.save(\n    ignore_permissions=flag,\n)\n")
        self.assertEqual(2, finding.line_number)

    def test_literal_false_none_and_defaults_are_not_findings(self):
        src = (
            "def f(ignore_permissions=False):\n"
            "    doc.save(ignore_permissions=False)\n"
            "    doc.insert(ignore_permissions=None)\n"
            "    if ignore_permissions == flag:\n        pass\n"
        )
        self.assertEqual([], self._scan(src))

    def test_literal_true_is_reported_once(self):
        self.assertEqual(1, len(self._scan("doc.save(ignore_permissions=True)\n")))


if __name__ == "__main__":
    unittest.main()
