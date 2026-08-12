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

    def _make_bench(self, root: Path, name: str = "frappe-bench") -> Path:
        bench = root / name
        (bench / "apps" / "verenigingen").mkdir(parents=True)
        (bench / "sites").mkdir()
        return bench

    def test_walks_up_from_a_start_to_find_the_bench(self):
        """A deep start resolves to the enclosing bench, however many levels up it is."""
        with tempfile.TemporaryDirectory() as d:
            bench = self._make_bench(Path(d))
            deep = bench / "apps" / "verenigingen" / "scripts" / "testing"
            deep.mkdir(parents=True)
            self.assertEqual(sts._bench_root(starts=(str(deep),)), str(bench))

    def test_file_location_takes_precedence_over_cwd(self):
        """Documented precedence: the bench the script lives in wins over the cwd's.

        Asserted through `starts` rather than by relying on where this test file sits. The
        first version of this test asserted the OPPOSITE (that cwd wins) and passed only
        because it was run from a worktree, where __file__ is outside any bench. Installed
        under a real bench, it failed -- a location-dependent test about location handling.
        """
        with tempfile.TemporaryDirectory() as d:
            script_bench = self._make_bench(Path(d), "bench-of-the-script")
            cwd_bench = self._make_bench(Path(d), "bench-of-the-cwd")
            resolved = sts._bench_root(starts=(str(script_bench), str(cwd_bench)))
            self.assertEqual(resolved, str(script_bench))

    def test_cwd_is_used_when_the_script_is_outside_any_bench(self):
        """The worktree case: __file__ is in a temp dir, so the cwd fallback must answer."""
        with tempfile.TemporaryDirectory() as d:
            orphan = Path(d) / "worktree-somewhere"
            orphan.mkdir()
            cwd_bench = self._make_bench(Path(d), "the-real-bench")
            resolved = sts._bench_root(starts=(str(orphan), str(cwd_bench)))
            self.assertEqual(resolved, str(cwd_bench))

    def test_a_dir_with_only_apps_is_not_a_bench(self):
        """Both markers are required; `apps/` alone is not enough to claim a bench."""
        with tempfile.TemporaryDirectory() as d:
            half = Path(d) / "not-a-bench"
            (half / "apps").mkdir(parents=True)
            self.assertIsNone(sts._bench_root(starts=(str(half),)))


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
