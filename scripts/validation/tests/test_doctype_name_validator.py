#!/usr/bin/env python3
"""Unit tests for scripts/validation/doctype_name_validator.py.

Pure-Python (no bench/site needed), except the two tests that exercise the
authority, which read the DocType JSONs on disk. Run with:
    python -m unittest scripts.validation.tests.test_doctype_name_validator
or plain:
    python scripts/validation/tests/test_doctype_name_validator.py

Every test here pairs a positive with its control. A detector that flags
everything and a detector that flags nothing both pass a one-sided test, and
this repo has shipped both.
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "doctype_name_validator.py"
_spec = importlib.util.spec_from_file_location("doctype_name_validator", _MOD_PATH)
dnv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dnv
_spec.loader.exec_module(dnv)


def _names(source, known=("Member", "Chapter", "Chapter Board Member")):
    """Unknown doctype names the scanner reports for one source string."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "sample.py"
        path.write_text(source)
        return sorted(f.name for f in dnv.unknown_in_file(path, dict.fromkeys(known, "app")))


class TestDetection(unittest.TestCase):
    def test_flags_an_unknown_name_and_not_a_known_one(self):
        found = _names(
            'import frappe\n'
            'frappe.db.exists("Chapter Board Member", {})\n'
            'frappe.db.exists("Verenigingen Chapter Board Member", {})\n'
        )
        self.assertEqual(found, ["Verenigingen Chapter Board Member"])

    def test_dict_literal_doctype_key(self):
        self.assertEqual(
            _names('import frappe\nfrappe.get_doc({"doctype": "Nope", "a": 1})\n'), ["Nope"]
        )
        self.assertEqual(
            _names('import frappe\nfrappe.get_doc({"doctype": "Member", "a": 1})\n'), []
        )

    def test_app_cleanup_registries_are_a_doctype_position(self):
        """#491 lived in these, and no frappe-shaped scan would have found it."""
        self.assertEqual(_names('self.track_doc("Nope", x)\n'), ["Nope"])
        self.assertEqual(_names('self._cleanup_manager.register("Nope", x)\n'), ["Nope"])
        self.assertEqual(_names('self.track_doc("Member", x)\n'), [])

    def test_non_literal_first_argument_is_ignored(self):
        """A variable's value is not knowable here; guessing is how a gate lies."""
        self.assertEqual(_names('import frappe\nfrappe.get_all(doctype_var)\n'), [])

    def test_doctype_probe_is_not_a_finding_and_exempts_the_file(self):
        source = (
            'import frappe\n'
            'if frappe.db.exists("DocType", "Optional Thing"):\n'
            '    frappe.db.count("Optional Thing")\n'
        )
        self.assertEqual(_names(source), [])
        # Control: the same call WITHOUT the probe is a finding, so the exemption
        # is doing work rather than the name being unreachable.
        self.assertEqual(
            _names('import frappe\nfrappe.db.count("Optional Thing")\n'), ["Optional Thing"]
        )

    def test_raw_tables_are_not_doctypes_and_are_exempt(self):
        self.assertEqual(_names('import frappe\nfrappe.db.delete("__Auth", {})\n'), [])
        self.assertEqual(_names('import frappe\nfrappe.db.delete("__Nope", {})\n'), ["__Nope"])

    def test_inline_suppression(self):
        self.assertEqual(
            _names('import frappe\nfrappe.get_all("Nope")  # doctype-ok: negative test\n'), []
        )
        self.assertEqual(_names('import frappe\nfrappe.get_all("Nope")\n'), ["Nope"])

    def test_unparseable_file_is_skipped_rather_than_crashing(self):
        self.assertEqual(_names("def (:\n"), [])


class TestAuthority(unittest.TestCase):
    """The authority is DocType JSONs on the bench, so it has to find the bench."""

    def test_bench_apps_resolves_past_a_worktree(self):
        known = dnv.known_doctypes()
        for required in ("User", "DocType", "Sales Invoice", "Member", "Chapter Board Member"):
            self.assertIn(
                required, known,
                f"{required!r} missing: BENCH_APPS resolved to {dnv.BENCH_APPS}, which is not "
                "the bench's apps/ directory (this is what a git worktree breaks)",
            )

    def test_the_role_names_behind_677_are_not_doctypes(self):
        known = dnv.known_doctypes()
        for role_name in (
            "Verenigingen Chapter Board Member",
            "Verenigingen Volunteer",
            "Verenigingen Chapter",
            "Verenigingen Volunteer Team",
        ):
            self.assertNotIn(role_name, known)
        for real in ("Chapter Board Member", "Volunteer", "Chapter", "Team"):
            self.assertIn(real, known)


class TestSelfCheck(unittest.TestCase):
    def test_self_check_passes(self):
        self.assertEqual(dnv.self_check(), 0)


class TestBaseline(unittest.TestCase):
    def test_baseline_round_trips(self):
        from collections import Counter

        counts = Counter({"a/b.py::Some DocType": 2, "c.py::Other": 1})
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "baseline.txt"
            dnv.write_baseline(path, counts)
            self.assertEqual(dnv.load_baseline(path), dict(counts))

    def test_committed_baseline_covers_the_tree(self):
        """A baseline that does not match is a gate that fires on unrelated edits."""
        counts, _ = dnv.census(dnv.SCAN_ROOTS)
        baseline = dnv.load_baseline(dnv.DEFAULT_BASELINE)
        grown = {k: v for k, v in counts.items() if v > baseline.get(k, 0)}
        self.assertEqual(
            grown, {},
            "the committed baseline is behind the tree; regenerate with --update-baseline",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
