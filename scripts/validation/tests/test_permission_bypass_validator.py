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


if __name__ == "__main__":
    unittest.main()
