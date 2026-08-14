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

    def test_app_path_form_survives_a_path_with_no_apps_component(self):
        """The worktree case: frappe's own split would raise here, `_dotted` must not."""
        test = ["/tmp/scratch/wt-269/verenigingen/tests/payment", "test_x.py"]
        self.assertEqual(
            sts._dotted(test, app_path="/tmp/scratch/wt-269/verenigingen"),
            "verenigingen.tests.payment.test_x",
        )

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


class FrappeTimingsKeyTest(unittest.TestCase):
    """`_frappe_timings_key` must reproduce frappe's limitation, not correct it."""

    def test_matches_frappe_for_a_normal_bench_path(self):
        key = sts._frappe_timings_key(
            "/home/x/frappe-bench/apps/verenigingen/verenigingen/tests/payment/test_x.py"
        )
        self.assertEqual(key, "verenigingen.tests.payment.test_x")

    def test_returns_none_when_there_is_no_apps_component(self):
        """This None is the whole detection: frappe finds no weight for such a path.

        If this ever starts returning a key, the "no measured weights" warning stops
        firing and the tool goes back to presenting a fallback layout as CI's.
        """
        self.assertIsNone(sts._frappe_timings_key("/tmp/scratch/wt/verenigingen/tests/test_x.py"))


class SeededSplitTest(unittest.TestCase):
    """The chaos partition (#328 mechanism 3).

    CI's own split is a pure function of the weights, so every PR draws the SAME
    co-tenancy and latent collisions surface only when an unrelated edit re-packs the
    bins. This permutes deliberately, and the seed is what makes a red draw
    reproducible -- so "same seed, same partition" is the property the whole mechanism
    rests on.
    """

    def _corpus(self, count=120):
        tests = [["", "apps", "app", "pkg", "tests", f"test_{i:03}.py"] for i in range(count)]
        weights = [1 + (i % 7) for i in range(count)]
        return tests, weights

    def test_the_same_seed_gives_the_same_partition(self):
        tests, weights = self._corpus()
        self.assertEqual(
            sts.seeded_split(tests, weights, 12, 4711),
            sts.seeded_split(tests, weights, 12, 4711),
        )

    def test_a_different_seed_gives_a_different_partition(self):
        """The test a no-op seed would fail."""
        tests, weights = self._corpus()
        self.assertNotEqual(
            sts.seeded_split(tests, weights, 12, 4711),
            sts.seeded_split(tests, weights, 12, 1234),
        )

    def test_a_different_seed_moves_files_BETWEEN_shards(self):
        """Membership, not just order -- and the two are separately breakable.

        Without this, dropping the placement shuffle entirely still passes
        `test_a_different_seed_gives_a_different_partition`, because the intra-shard
        shuffle alone makes the lists differ. The whole point is new NEIGHBOURS.
        """
        tests, weights = self._corpus()
        one = {frozenset(tuple(t) for t in chunk) for chunk in sts.seeded_split(tests, weights, 12, 4711)}
        two = {frozenset(tuple(t) for t in chunk) for chunk in sts.seeded_split(tests, weights, 12, 1234)}
        self.assertNotEqual(one, two)

    def test_it_loses_nothing_and_duplicates_nothing(self):
        tests, weights = self._corpus()
        chunks = sts.seeded_split(tests, weights, 12, 99)
        flat = [t for chunk in chunks for t in chunk]
        self.assertEqual(len(tests), len(flat))
        self.assertEqual(sorted(map(tuple, tests)), sorted(map(tuple, flat)))

    def test_it_returns_exactly_the_requested_number_of_shards(self):
        tests, weights = self._corpus()
        self.assertEqual(12, len(sts.seeded_split(tests, weights, 12, 99)))

    def test_no_shard_overshoots_the_target_by_more_than_one_file(self):
        """Random-order greedy trades LPT's balance for varied co-tenancy.

        The bound is what makes that trade acceptable: placing each file into the
        lightest bin means a bin can only exceed the mean by the last file it took.
        """
        tests, weights = self._corpus()
        chunks = sts.seeded_split(tests, weights, 12, 7)
        by_path = {"/".join(t): w for t, w in zip(tests, weights, strict=True)}
        totals = [sum(by_path["/".join(t)] for t in chunk) for chunk in chunks]
        self.assertLessEqual(max(totals), sum(weights) / 12 + max(weights))

    def test_execution_order_inside_a_shard_is_permuted_too(self):
        """Co-tenancy is only half of order-dependence.

        CI sorts each shard alphabetically, so "B only passes when A ran first" is
        stable there. If this returned sorted chunks it would find nothing CI does not.
        """
        tests, weights = self._corpus()
        chunks = sts.seeded_split(tests, weights, 12, 7)
        self.assertTrue(
            any(chunk != sorted(chunk) for chunk in chunks),
            "every shard came back in sorted order, so the seed did not permute order",
        )

    def test_the_partition_does_not_depend_on_the_input_order(self):
        """Replay has to survive frappe walking the tree in a different order.

        Otherwise a seed reproduces a layout only on the machine that drew it.
        """
        tests, weights = self._corpus()
        pairs = list(zip(tests, weights, strict=True))[::-1]
        reversed_tests = [t for t, _ in pairs]
        reversed_weights = [w for _, w in pairs]
        self.assertEqual(
            sts.seeded_split(tests, weights, 12, 4711),
            sts.seeded_split(reversed_tests, reversed_weights, 12, 4711),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
