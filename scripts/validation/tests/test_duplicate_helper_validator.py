#!/usr/bin/env python3
"""Unit tests for scripts/validation/duplicate_helper_validator.py.

Pure-Python (no bench/site needed). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_duplicate_helper_validator.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "duplicate_helper_validator.py"
_spec = importlib.util.spec_from_file_location("duplicate_helper_validator", _MOD_PATH)
dhv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dhv
_spec.loader.exec_module(dhv)


def _census(files: dict):
    """Build a temp tree from {relative path: source} and return the census."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for rel, src in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src)
        return dhv.census(str(root))


class WhatCountsTest(unittest.TestCase):
    def test_a_private_helper_in_two_files_is_counted(self):
        src = "def _persist_company():\n    pass\n"
        self.assertEqual({"_persist_company": 2}, _census({"a.py": src, "b.py": src}))

    def test_a_helper_in_one_file_only_is_not_counted(self):
        self.assertEqual({}, _census({"a.py": "def _solo():\n    pass\n"}))

    def test_public_names_are_ignored(self):
        """Frappe REQUIRES these names per module -- `execute` in every report,
        `get_context` in every page, `run_tests` in every suite. Counting them
        reports 273 names of which the top four are framework contract, not
        duplication. Restricting to the leading underscore is what makes this
        census 71 real names instead."""
        src = "def execute():\n    pass\ndef get_context(context):\n    pass\n"
        self.assertEqual({}, _census({"a.py": src, "b.py": src}))

    def test_dunder_names_are_ignored(self):
        src = "def __getattr__(name):\n    pass\n"
        self.assertEqual({}, _census({"a.py": src, "b.py": src}))

    def test_methods_are_not_module_level_helpers(self):
        """A method is scoped by its class; the copy-paste unit here is the
        module-level helper."""
        src = "class T:\n    def _helper(self):\n        pass\n"
        self.assertEqual({}, _census({"a.py": src, "b.py": src}))

    def test_two_helpers_in_the_SAME_file_are_one_file(self):
        """The census counts FILES, not definitions: a helper redefined in one
        module is a different problem (and a syntax-level one)."""
        src = "def _a():\n    pass\n\ndef _a():\n    pass\n"
        self.assertEqual({}, _census({"a.py": src}))

    def test_an_unparseable_file_is_skipped_not_fatal(self):
        good = "def _shared():\n    pass\n"
        self.assertEqual(
            {}, _census({"a.py": good, "b.py": "def ( this is not python\n"})
        )


class PruningTest(unittest.TestCase):
    def test_vendor_and_worktree_copies_are_pruned(self):
        """Without this the census counts agent worktrees under .claude/, which
        made the sibling enforcer scan 12,574 files instead of 1,398."""
        src = "def _shared():\n    pass\n"
        got = _census(
            {
                "pkg/a.py": src,
                "pkg/b.py": src,
                ".claude/worktrees/x/pkg/a.py": src,
                "node_modules/y/a.py": src,
            }
        )
        self.assertEqual({"_shared": 2}, got)


class RatchetTest(unittest.TestCase):
    def test_a_newly_duplicated_helper_fails(self):
        self.assertTrue(dhv.regressions({"_new": 2}, {}))

    def test_a_baselined_helper_at_the_same_count_passes(self):
        self.assertFalse(dhv.regressions({"_known": 8}, {"_known": 8}))

    def test_one_more_copy_of_a_baselined_helper_fails(self):
        """The case this exists for: someone adds a ninth _persist_eur_company."""
        self.assertTrue(dhv.regressions({"_known": 9}, {"_known": 8}))

    def test_fewer_copies_passes(self):
        """Consolidation is the point; it must never be what fails the gate."""
        self.assertFalse(dhv.regressions({"_known": 3}, {"_known": 8}))


class BaselineIOTest(unittest.TestCase):
    def test_a_written_baseline_reads_back_identically(self):
        counts = {"_persist_eur_company": 8, "_payment": 13}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "baseline.txt"
            dhv.write_baseline(p, counts)
            self.assertEqual(counts, dhv.load_baseline(p))

    def test_comments_and_blanks_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "baseline.txt"
            p.write_text("# a comment\n\n_thing::4\n")
            self.assertEqual({"_thing": 4}, dhv.load_baseline(p))


class WholeTreeTest(unittest.TestCase):
    """Pinned totals. Without a hard number, every test above is satisfied by a
    census that finds nothing."""

    @classmethod
    def setUpClass(cls):
        # No argument: measure exactly what the gate measures. Passing REPO_ROOT
        # here would scan scripts/ too and pin a number the gate never computes.
        cls.counts = dhv.census()

    def test_the_census_is_not_empty(self):
        self.assertGreater(len(self.counts), 40, "the census stopped finding helpers")

    def test_the_known_worst_offender_is_present(self):
        """8 copies of this helper are why #394 exists: two were fixed to stop
        borrowing a company by currency, and the third was missed."""
        self.assertGreaterEqual(self.counts.get("_persist_eur_company", 0), 3)

    def test_no_framework_entry_point_leaked_in(self):
        for name in ("execute", "get_context", "run_tests", "get_data", "get_columns"):
            self.assertNotIn(name, self.counts)


if __name__ == "__main__":
    unittest.main()
