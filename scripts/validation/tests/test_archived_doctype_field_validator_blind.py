#!/usr/bin/env python3
"""End-to-end tests for scripts/validation/archived/doctype_field_validator.py as the
`doctype-field-validator` pre-commit hook runs it (#2960).

The hook (`--pre-commit --reduced-fp-mode`, repo-relative filenames) reported nothing for three
causes, all hidden by validate_file's `except Exception: pass`: an unescaped `.format(` regex
(re.error on every finding), `relative_to(app_path)` on a repo-relative path, and a hardcoded
`/home/frappe/...` app path in main().

Each case builds a synthetic app in a temp dir and copies the real validator and its helpers
into its `scripts/validation/`, so `main()` resolves the app root exactly as the hook does.
Stdlib only.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_VALIDATION = Path(__file__).resolve().parents[1]
_HELPERS = ("doctype_loader.py", "bench_resolution.py")

_MEMBER = {
    "doctype": "DocType",
    "name": "Member",
    "fields": [{"fieldname": "full_name", "fieldtype": "Data"}],
}
_MISSING = "def f():\n    member = frappe.get_doc('Member', 'x')\n    return member.zzz_no_such_field\n"
_VALID = "def f():\n    member = frappe.get_doc('Member', 'x')\n    return member.full_name\n"


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
    (tools / "archived").mkdir(parents=True)
    for name in _HELPERS:
        shutil.copy(_VALIDATION / name, tools / name)
    shutil.copy(_VALIDATION / "archived" / "doctype_field_validator.py", tools / "archived")


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    script = root / "scripts" / "validation" / "archived" / "doctype_field_validator.py"
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=root, capture_output=True, text=True, timeout=120
    )


# The hook's own flags.
_HOOK = ("--pre-commit", "--reduced-fp-mode")


class _AppCase(unittest.TestCase):
    sources: dict = {}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "app"
        self.root.mkdir()
        _build_app(self.root, self.sources)
        self.baseline = self.root / "scripts" / "validation" / "doctype_field_validator_baseline.txt"


class HookSeesTests(_AppCase):
    sources = {"missing.py": _MISSING, "valid.py": _VALID}

    def test_a_missing_field_is_reported_for_a_repo_relative_file(self):
        # RED on develop: re.error on '.format(' and relative_to ValueError, both swallowed.
        result = _run(self.root, *_HOOK, "--no-baseline", "verenigingen/services/missing.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("zzz_no_such_field not in Member", result.stdout)

    def test_a_valid_reference_is_not_reported(self):
        # Control: the hook is not simply failing on everything.
        result = _run(self.root, *_HOOK, "--no-baseline", "verenigingen/services/valid.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("not in Member", result.stdout)

    def test_the_app_scan_finds_the_app_without_a_hardcoded_path(self):
        # RED on develop: main() scanned /home/frappe/frappe-bench/apps/verenigingen.
        result = _run(self.root, *_HOOK, "--no-baseline")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("missing.py", result.stdout)
        self.assertNotIn("valid.py:", result.stdout)

    def test_a_file_that_cannot_be_processed_is_surfaced_on_stderr(self):
        # RED on develop: `except Exception: pass`. A syntax error is a skip, a real fault is not;
        # make the file unreadable as UTF-8 to provoke a non-SyntaxError failure.
        bad = self.root / "verenigingen" / "services" / "bad.py"
        bad.write_bytes(b"x = '\xff\xfe'\n")
        result = _run(self.root, *_HOOK, "--no-baseline", "verenigingen/services/bad.py")
        self.assertIn("bad.py", result.stderr)


class ScanAndHookAgreeTests(_AppCase):
    sources = {"missing.py": _MISSING}

    def test_a_test_file_passed_by_the_hook_is_skipped_like_the_scan_skips_it(self):
        # The hook's own exclude only matches a top-level tests/, so pre-commit hands us
        # verenigingen/tests/...; the app scan skips those, and the baseline is built from the scan.
        test_file = self.root / "verenigingen" / "tests" / "test_x.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(_MISSING)
        result = _run(self.root, *_HOOK, "--no-baseline", "verenigingen/tests/test_x.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Control: the same content outside tests/ is reported.
        result = _run(self.root, *_HOOK, "--no-baseline", "verenigingen/services/missing.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


class RatchetTests(_AppCase):
    sources = {"missing.py": _MISSING, "valid.py": _VALID}

    def test_update_baseline_records_the_finding_without_a_line_number(self):
        result = _run(self.root, "--update-baseline")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        entries = [ln for ln in self.baseline.read_text().splitlines() if ln and not ln.startswith("#")]
        self.assertEqual(entries, ["verenigingen/services/missing.py::Member::zzz_no_such_field::1"])

    def test_baselined_findings_pass(self):
        _run(self.root, "--update-baseline")
        result = _run(self.root, *_HOOK, "verenigingen/services/missing.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 baselined high-confidence finding(s) suppressed", result.stdout)

    def test_a_new_finding_fails(self):
        _run(self.root, "--update-baseline")
        (self.root / "verenigingen" / "services" / "added.py").write_text(_MISSING)
        result = _run(self.root, *_HOOK, "verenigingen/services/added.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("added.py", result.stdout)

    def test_a_higher_count_for_a_baselined_key_fails(self):
        _run(self.root, "--update-baseline")
        path = self.root / "verenigingen" / "services" / "missing.py"
        path.write_text(
            _MISSING + "\n\ndef g():\n    member = frappe.get_doc('Member', 'y')\n    return member.zzz_no_such_field\n"
        )
        result = _run(self.root, *_HOOK, "verenigingen/services/missing.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_missing_baseline_baselines_nothing(self):
        # Control: without the file the same finding fails, so the passes above come from it.
        result = _run(self.root, *_HOOK, "verenigingen/services/missing.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
