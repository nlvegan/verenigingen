#!/usr/bin/env python3
"""Unit tests for issue #1076: whitelist_type_safety_validator.py's `--directory`
CLI default was hardcoded to `verenigingen/api`, and its pre-commit hook's own
`files:` filter (`^verenigingen/.*\\.py$`) never even triggers the script for a
`scripts/`-only change -- same class as #1069's fix to the sibling API security
validators. `scripts/` is a real importable package holding dispatch-reachable
`frappe.whitelisted` endpoints of its own, and none of them were ever checked for
a missing type annotation or permission check.

Pure-Python (no bench/site needed). Builds a temp tree with BOTH a
`verenigingen/api/` file and a `scripts/` file and invokes the real CLI
(subprocess, exactly how the pre-commit/pre-push hook would) with no arguments.
Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_whitelist_type_safety_validator.py
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "security" / "whitelist_type_safety_validator.py"

# Missing type annotation on `member_id` -- a real ERROR-severity finding.
UNTYPED_ENDPOINT_SRC = (
    "import frappe\n\n"
    "@frappe.whitelist()\n"
    "def get_untyped_member(member_id):\n"
    "    doc = frappe.get_doc('Member', member_id)\n"
    "    return doc.name\n"
)

# Fully type-annotated -- no ERROR finding.
TYPED_ENDPOINT_SRC = (
    "import frappe\n\n"
    "@frappe.whitelist()\n"
    "def get_typed_member(member_id: str):\n"
    "    doc = frappe.get_doc('Member', member_id)\n"
    "    doc.check_permission('read')\n"
    "    return doc.name\n"
)


def _run(cwd, extra_args=None):
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT)] + (extra_args or []),
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


class _FakeAppTree(unittest.TestCase):
    """<tmp>/verenigingen/api/typed.py (clean) + <tmp>/scripts/untyped.py
    (one ERROR finding) -- mirrors a real repo root closely enough for the CLI's
    relative 'verenigingen/api' / 'scripts' scan roots to resolve."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)

        api_dir = self.root / "verenigingen" / "api"
        api_dir.mkdir(parents=True)
        (api_dir / "typed.py").write_text(TYPED_ENDPOINT_SRC)

        scripts_dir = self.root / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "untyped.py").write_text(UNTYPED_ENDPOINT_SRC)

    def tearDown(self):
        self._tmpdir.cleanup()


class DefaultScanCoversBothRootsTest(_FakeAppTree):
    """These tests never call --update-baseline: the real committed
    whitelist_type_safety_scripts_baseline.txt sits next to the validator at a
    FIXED path (matching the sibling api_security_validator.py /
    insecure_api_detector.py convention, and their tests' own choice not to
    exercise the write side against that real file). Writing to it from a
    test -- even with a restore in a `finally` -- risks leaving the real,
    committed file mutated if the process is killed mid-test, so the
    generic load/write/partition round-trip is left to
    test_scripts_dir_baseline.py's own isolated-tempfile tests; what these
    tests prove is specific to THIS validator: which roots main() scans by
    default, and that a brand-new (guaranteed-not-baselined) finding blocks."""

    def test_default_run_finds_the_scripts_error_and_blocks(self):
        """RED: a brand-new scripts/ finding, no baseline written yet, must
        block -- exactly the shape a real new violation takes."""
        rc, output = _run(self.root)
        self.assertNotEqual(
            0, rc, f"a fresh ERROR under scripts/ must fail the gate. Output:\n{output}"
        )
        self.assertIn("get_untyped_member", output)

    def test_default_run_also_scans_the_verenigingen_api_root(self):
        """Confirms the default is BOTH roots, not scripts/ alone -- the typed
        (clean) verenigingen/api/ file must be counted, so "Files checked"
        reflects both trees having been walked."""
        rc, output = _run(self.root)
        self.assertIn("typed.py", output)

    def test_a_fresh_finding_under_verenigingen_api_always_blocks(self):
        """The zero-tolerance half of the split: verenigingen/api/ findings
        are never read from (or written to) any baseline -- proven here
        without ever invoking --update-baseline, so this cannot mutate the
        real committed file."""
        (self.root / "verenigingen" / "api" / "also_untyped.py").write_text(
            UNTYPED_ENDPOINT_SRC.replace("get_untyped_member", "also_untyped_member")
        )
        rc, output = _run(self.root)
        self.assertNotEqual(
            0, rc, f"an untyped verenigingen/api/ endpoint must always block. Output:\n{output}"
        )
        self.assertIn("also_untyped_member", output)


class NoScanRootsFoundTest(unittest.TestCase):
    """#1078's fail-open regression, applied to this validator: a misconfigured
    run (wrong cwd) that finds NEITHER scan root must hard-fail, not silently
    report success."""

    def test_cli_exits_non_zero_when_neither_root_exists(self):
        with tempfile.TemporaryDirectory() as d:
            rc, output = _run(d)
            self.assertNotEqual(
                0, rc, f"a run that finds no scan root must exit non-zero. Output:\n{output}"
            )


class ExplicitDirectoryArgumentIsUnchangedTest(_FakeAppTree):
    """--directory verenigingen/api (or any single explicit directory) must
    keep behaving exactly as before #1076 -- single root, no scripts/ baseline
    consulted, no widening."""

    def test_explicit_directory_scans_only_that_root(self):
        rc, output = _run(self.root, ["--directory", "verenigingen/api"])
        self.assertEqual(0, rc, f"the clean, explicitly-scoped root must pass. Output:\n{output}")
        self.assertNotIn("get_untyped_member", output)


if __name__ == "__main__":
    unittest.main()
