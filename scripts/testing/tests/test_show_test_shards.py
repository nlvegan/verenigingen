#!/usr/bin/env python3
"""Unit tests for scripts/testing/show_test_shards.py.

Pure-Python (no bench/site needed): these cover the two helpers that do not touch frappe.
`_bench_root` is here because it shipped broken the first time -- it hopped a fixed number
of `..` from __file__, which is right for the installed checkout at
<bench>/apps/verenigingen/scripts/testing/ and silently wrong when the same file is run
from a git worktree, where it resolved to an unrelated temp directory and the script then
reported "no default_site".

Run with:  python -m pytest this_file.py
or plain:  python scripts/testing/tests/test_show_test_shards.py
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "show_test_shards.py"
_spec = importlib.util.spec_from_file_location("show_test_shards", _MOD_PATH)
sts = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sts
_spec.loader.exec_module(sts)


class BenchRootTest(unittest.TestCase):
    """A bench is any ancestor holding both apps/ and sites/."""

    def test_explicit_override_wins(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(sts._bench_root(d), os.path.abspath(d))

    def test_finds_bench_from_cwd_regardless_of_depth(self):
        """The worktree case: the script is nowhere near the bench, so cwd has to work."""
        with tempfile.TemporaryDirectory() as d:
            bench = Path(d) / "frappe-bench"
            (bench / "apps" / "verenigingen").mkdir(parents=True)
            (bench / "sites").mkdir()
            deep = bench / "apps" / "verenigingen" / "scripts" / "testing"
            deep.mkdir(parents=True)
            prev = os.getcwd()
            os.chdir(deep)
            try:
                self.assertEqual(sts._bench_root(), str(bench))
            finally:
                os.chdir(prev)

    def test_a_dir_with_only_apps_is_not_a_bench(self):
        """Both markers are required; `apps/` alone is not enough to claim a bench."""
        with tempfile.TemporaryDirectory() as d:
            half = Path(d) / "not-a-bench"
            (half / "apps").mkdir(parents=True)
            prev = os.getcwd()
            os.chdir(half)
            try:
                # Either None, or some real bench above the temp dir -- but never this one.
                self.assertNotEqual(sts._bench_root(), str(half))
            finally:
                os.chdir(prev)


class DottedPathTest(unittest.TestCase):
    """Dotted names must match test_timings.json keys and --modules input."""

    def test_strips_app_prefix_and_extension(self):
        test = ["/home/x/frappe-bench/apps/verenigingen/verenigingen/tests/payment", "test_mt940.py"]
        self.assertEqual(sts._dotted(test), "verenigingen.tests.payment.test_mt940")

    def test_a_bench_path_containing_apps_skews_the_name_like_frappe_does(self):
        """KNOWN LIMITATION, shared with frappe on purpose.

        The conversion splits on the FIRST "/apps/" and then drops one component, so a
        bench living under a directory called `apps` yields a skewed dotted name. This
        mirrors `get_test_weight` in frappe/parallel_test_runner.py verbatim, and that is
        the point: these names are looked up in test_timings.json, whose keys frappe
        generated with exactly this logic. "Correcting" it here would produce names that
        no longer match the table, so the behaviour is pinned rather than fixed.
        """
        test = ["/srv/apps/frappe-bench/apps/verenigingen/verenigingen/tests", "test_x.py"]
        self.assertEqual(sts._dotted(test), "apps.verenigingen.verenigingen.tests.test_x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
