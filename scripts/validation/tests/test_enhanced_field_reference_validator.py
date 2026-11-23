#!/usr/bin/env python3
"""Unit tests for scripts/validation/enhanced_field_reference_validator.py (#2323).

The validator was blind: `child_table_patterns` / `property_patterns` were assigned after a
`return`, so every file that reached the child-table exclusion raised AttributeError, which
`validate_file` swallowed, and the run reported "No field reference issues found!".

Each case builds a small synthetic app under a temp dir and copies the real validator into
its `scripts/validation/`, so `main()` resolves the app root exactly as in CI. Stdlib only.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_VALIDATION = Path(__file__).resolve().parents[1]
_SCRIPTS = ("enhanced_field_reference_validator.py", "doctype_loader.py", "bench_resolution.py")

_MEMBER = {
    "doctype": "DocType",
    "name": "Member",
    "fields": [{"fieldname": "full_name", "fieldtype": "Data"}],
}
_MISSING = "def f():\n    member = frappe.get_doc('Member', 'x')\n    return member.zzz_no_such_field\n"
_VALID = "def f():\n    member = frappe.get_doc('Member', 'x')\n    return member.full_name\n"
# `member` here is a child row, not a Member: the child-table exclusion must keep it quiet.
_CHILD_ROW = (
    "def f(self):\n"
    "    for member in self.team_members:\n"
    "        print(member.team_role)\n"
)


def _build_app(root: Path, sources: dict) -> None:
    (root / "pyproject.toml").write_text('[project]\nname = "verenigingen"\n')
    doctype_dir = root / "verenigingen" / "verenigingen" / "doctype" / "member"
    doctype_dir.mkdir(parents=True)
    (doctype_dir / "member.json").write_text(json.dumps(_MEMBER))
    for rel, src in sources.items():
        path = root / "verenigingen" / "services" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src)
    tools = root / "scripts" / "validation"
    tools.mkdir(parents=True)
    for name in _SCRIPTS:
        shutil.copy(_VALIDATION / name, tools / name)


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    script = root / "scripts" / "validation" / "enhanced_field_reference_validator.py"
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=root, capture_output=True, text=True, timeout=120
    )


class _AppCase(unittest.TestCase):
    sources: dict = {}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "app"
        self.root.mkdir()
        _build_app(self.root, self.sources)
        self.baseline = self.root / "scripts" / "validation" / "field_reference_baseline.txt"


class ValidatorSeesTests(_AppCase):
    sources = {"missing.py": _MISSING, "valid.py": _VALID, "child.py": _CHILD_ROW}

    def test_a_missing_field_is_reported(self):
        # RED on develop: AttributeError on child_table_patterns, swallowed, exit 0.
        result = _run(self.root, "--pre-commit", "--no-baseline")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("zzz_no_such_field not in Member", result.stdout)

    def test_a_valid_reference_and_a_child_row_are_not_reported(self):
        # Controls: the same run reports only the seeded finding, so a valid field and a
        # child-table iteration (the exclusion that used to crash) stay quiet.
        result = _run(self.root, "--pre-commit", "--no-baseline")
        self.assertIn("Found 1 field reference issues", result.stdout)
        self.assertNotIn("full_name not in", result.stdout)
        self.assertNotIn("team_role not in", result.stdout)

    def test_a_relative_file_argument_is_validated(self):
        # pre-commit passes repo-relative paths; relative_to() on one used to raise and be swallowed.
        result = _run(self.root, "--no-baseline", "verenigingen/services/missing.py")
        self.assertEqual(result.returncode, 1, result.stdout)


class RatchetTests(_AppCase):
    sources = {"missing.py": _MISSING, "valid.py": _VALID}

    def test_update_baseline_records_the_finding_without_a_line_number(self):
        result = _run(self.root, "--update-baseline")
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = [
            ln for ln in self.baseline.read_text().splitlines() if ln and not ln.startswith("#")
        ]
        self.assertEqual(entries, ["verenigingen/services/missing.py::Member::zzz_no_such_field::1"])

    def test_baselined_findings_pass(self):
        _run(self.root, "--update-baseline")
        result = _run(self.root, "--pre-commit")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 baselined finding(s) suppressed", result.stdout)

    def test_a_new_finding_fails(self):
        _run(self.root, "--update-baseline")
        extra = self.root / "verenigingen" / "services" / "added.py"
        extra.write_text(_MISSING)
        result = _run(self.root, "--pre-commit")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("added.py", result.stdout)

    def test_a_higher_count_for_a_baselined_key_fails(self):
        _run(self.root, "--update-baseline")
        path = self.root / "verenigingen" / "services" / "missing.py"
        path.write_text(_MISSING + "\n\ndef g():\n    member = frappe.get_doc('Member', 'y')\n    return member.zzz_no_such_field\n")
        result = _run(self.root, "--pre-commit")
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_a_missing_baseline_baselines_nothing(self):
        # Control: without the file, the same finding fails, so the passes above come from the baseline.
        result = _run(self.root, "--pre-commit")
        self.assertEqual(result.returncode, 1, result.stdout)


if __name__ == "__main__":
    unittest.main()
