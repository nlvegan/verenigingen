#!/usr/bin/env python3
"""Unit tests for scripts/testing/select_pr_test_modules.py (the PR-side module selector).

Pure Python: builds a throwaway git repo shaped like the app, makes a "PR" commit, and asks
the selector what it would run. The census-file tests run against the REAL tree.

Run with:  python -m unittest discover -s scripts/testing/tests -p 'test_select_pr_test_modules.py'
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "select_pr_test_modules.py"
_spec = importlib.util.spec_from_file_location("select_pr_test_modules", _MOD_PATH)
sel = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sel
_spec.loader.exec_module(sel)

REAL_ROOT = _MOD_PATH.parents[2]

TEST_SRC = "import unittest\nclass TestX(unittest.TestCase):\n    def test_a(self):\n        pass\n"
HELPER_SRC = "class TestDataContext:\n    pass\n\ndef make():\n    return 1\n"
# A shared base class: derives from TestCase but defines no test method (#2352,
# tests/utils/test_base_framework.py). `bench run-tests` on it prints no OK line.
BASE_ONLY_SRC = ("import unittest\nclass VerenigingenTestCase(unittest.TestCase):\n"
                 "    def setUp(self):\n        pass\n")
CENSUS_MOD = "verenigingen.tests.test_census_one"


def _git(root, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root, check=True, capture_output=True,
    )


class SelectorCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _git(self.root, "init", "-q")
        self.write("verenigingen/tests/test_census_one.py", TEST_SRC)
        self.write("verenigingen/tests/test_untouched.py", TEST_SRC)
        self.write("verenigingen/utils/stale.py", "x = 1\n")
        self.write("verenigingen/tests/test_stale_thing.py", TEST_SRC)
        self.write("verenigingen/tests/test_gone.py", TEST_SRC)
        self.write("verenigingen/tests/helper_mod.py", HELPER_SRC)
        self.census = self.root / "census.txt"
        self.census.write_text(f"# c\n{CENSUS_MOD}  # trailing\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "base")
        self.base = self.rev()

    def rev(self):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True,
                              text=True, check=True).stdout.strip()

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def pick(self, **kw):
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "pr", "--allow-empty")
        changed = sel.changed_paths(self.base, "HEAD", cwd=self.root)
        return sel.select(self.root, changed, census_file=self.census, **kw)


class SelectionRules(SelectorCase):
    def test_census_alone_when_pr_touches_nothing_testable(self):
        self.write("README.md", "hi")
        self.assertEqual(self.pick(), [CENSUS_MOD])

    def test_own_changed_test_module_is_picked_with_the_census(self):
        self.write("verenigingen/tests/test_new_thing.py", TEST_SRC)
        self.assertEqual(self.pick(), [CENSUS_MOD, "verenigingen.tests.test_new_thing"])

    def test_deleted_test_module_is_skipped(self):
        (self.root / "verenigingen/tests/test_gone.py").unlink()
        self.assertEqual(self.pick(), [CENSUS_MOD])

    def test_rename_runs_the_new_name_only(self):
        _git(self.root, "mv", "verenigingen/tests/test_gone.py", "verenigingen/tests/test_moved.py")
        self.assertEqual(self.pick(), [CENSUS_MOD, "verenigingen.tests.test_moved"])

    def test_helper_only_module_without_a_test_class_is_skipped(self):
        self.write("verenigingen/tests/test_helperish.py", HELPER_SRC)
        self.assertEqual(self.pick(), [CENSUS_MOD])

    def test_derived_module_with_only_a_base_class_is_skipped_but_a_real_test_is_kept(self):
        # #2352: editing a base.py derives every test_base_* module. The base-class-only one
        # runs 0 tests and reds the job; its namesake with a real test must still run.
        self.write("verenigingen/tests/utils/base.py", "x = 1\n")
        self.write("verenigingen/tests/utils/test_base_framework.py", BASE_ONLY_SRC)
        self.write("verenigingen/tests/utils/test_base_real.py", TEST_SRC)
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "base2")
        self.base = self.rev()
        self.write("verenigingen/tests/utils/base.py", "x = 2\n")
        log = []
        got = self.pick(log=log.append)
        self.assertNotIn("verenigingen.tests.utils.test_base_framework", got)
        self.assertIn("verenigingen.tests.utils.test_base_real", got)
        self.assertTrue([m for m in log if "test_base_framework" in m and "no test method" in m], log)

    def test_own_module_that_only_defines_a_base_class_is_skipped_with_a_reason(self):
        self.write("verenigingen/tests/test_only_base.py", BASE_ONLY_SRC)
        log = []
        self.assertEqual(self.pick(log=log.append), [CENSUS_MOD])
        self.assertTrue([m for m in log if "test_only_base" in m and "no test method" in m], log)

    def test_subclass_of_an_imported_base_may_inherit_tests_and_is_kept(self):
        # The base lives in another module: its tests cannot be seen here, so do not exclude.
        self.write("verenigingen/tests/test_inherits.py",
                   "from verenigingen.tests.shared import SharedTestCase\nclass TestY(SharedTestCase):\n    pass\n")
        self.assertIn("verenigingen.tests.test_inherits", self.pick())

    def test_subclass_of_a_local_testless_base_is_skipped(self):
        self.write("verenigingen/tests/test_chain.py", BASE_ONLY_SRC +
                   "class PerfCase(VerenigingenTestCase):\n    pass\n")
        self.assertEqual(self.pick(), [CENSUS_MOD])

    def test_local_mixin_defining_tests_keeps_the_module(self):
        self.write("verenigingen/tests/test_mixin.py",
                   "from frappe.tests import FrappeTestCase\nclass Mixin:\n    def test_a(self):\n        pass\n"
                   "class TestX(Mixin, FrappeTestCase):\n    pass\n")
        self.assertIn("verenigingen.tests.test_mixin", self.pick())

    def test_non_test_file_pulls_its_namesake_test(self):
        self.write("verenigingen/utils/stale.py", "x = 2\n")
        self.assertIn("verenigingen.tests.test_stale_thing", self.pick())

    def test_non_test_file_pulls_a_test_that_names_its_module(self):
        self.write("verenigingen/utils/imported_thing.py", "x = 1\n")
        self.write("verenigingen/tests/test_user.py",
                   TEST_SRC + "\nfrom verenigingen.utils.imported_thing import x\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "base2")
        self.base = self.rev()
        self.write("verenigingen/utils/imported_thing.py", "x = 2\n")
        self.assertIn("verenigingen.tests.test_user", self.pick())

    def test_derived_cap_bounds_derived_modules_but_not_own_or_census(self):
        for i in range(6):
            self.write(f"verenigingen/tests/test_stale_{i}.py", TEST_SRC)
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "base2")
        self.base = self.rev()
        self.write("verenigingen/utils/stale.py", "x = 3\n")
        got = self.pick(derived_cap=2)
        self.assertEqual(len([m for m in got if m != CENSUS_MOD]), 2)
        self.assertIn(CENSUS_MOD, got)

    def test_own_cap_trims_own_modules_never_the_census(self):
        for i in range(5):
            self.write(f"verenigingen/tests/test_sweep_{i}.py", TEST_SRC)
        got = self.pick(own_cap=2)
        self.assertEqual(len(got), 3)
        self.assertIn(CENSUS_MOD, got)

    def test_budget_drops_lowest_priority_extras_and_keeps_the_census(self):
        for i in range(3):
            self.write(f"verenigingen/tests/test_big_{i}.py", TEST_SRC)
        # own modules come before derived ones, in order; each costs timing + overhead.
        t = {"verenigingen.tests.test_big_0": 100, "verenigingen.tests.test_big_1": 100,
             "verenigingen.tests.test_big_2": 100}
        budget = 2 * (100 + sel.MODULE_OVERHEAD_SECONDS)
        warnings = []
        got = self.pick(timings=t, budget=budget, log=warnings.append)
        self.assertEqual(sorted(got), sorted([CENSUS_MOD, "verenigingen.tests.test_big_0", "verenigingen.tests.test_big_1"]))
        dropped = [w for w in warnings if w.startswith("::warning::") and "test_big_2" in w]
        self.assertEqual(len(dropped), 1, warnings)

    def test_budget_never_drops_the_census_even_when_it_alone_exceeds_it(self):
        self.assertEqual(self.pick(timings={CENSUS_MOD: 10_000}, budget=1), [CENSUS_MOD])

    def test_a_module_without_a_recorded_timing_costs_the_conservative_default(self):
        self.write("verenigingen/tests/test_unknown.py", TEST_SRC)
        cost = sel.UNKNOWN_MODULE_SECONDS + sel.MODULE_OVERHEAD_SECONDS
        self.assertEqual(sel.estimate("verenigingen.tests.test_unknown", {}), cost)
        self.assertIn("verenigingen.tests.test_unknown", self.pick(timings={}, budget=cost))
        self.assertNotIn("verenigingen.tests.test_unknown", self.pick(timings={}, budget=cost - 1))

    def test_a_dropped_smaller_module_after_a_too_big_one_is_still_tried(self):
        got = sel.within_budget(["a.b", "c.d"], {"a.b": 500, "c.d": 5}, 100, lambda _m: None)
        self.assertEqual(got, ["c.d"])

    def test_the_committed_timings_table_loads(self):
        t = sel.load_timings()
        self.assertGreater(len(t), 100)
        self.assertTrue(all(isinstance(v, (int, float)) for v in t.values()))

    def test_hostile_file_names_never_reach_the_output(self):
        for name in ("test_$(touch pwned).py", "test_a b.py", "test_a;b.py", "test_`x`.py",
                     "test_quo'te.py", "test_dash-ed.py", "test_new\nline.py", "test_trail.py\n"):
            self.write(f"verenigingen/tests/{name}", TEST_SRC)
        got = self.pick()
        self.assertEqual(got, [CENSUS_MOD])
        for m in got:
            self.assertRegex(m, sel._SAFE_MODULE)

    def test_trailing_newline_in_a_name_is_not_a_safe_path(self):
        # `$` matches before a trailing newline; fullmatch must not.
        self.assertIsNone(sel._SAFE_PATH.fullmatch("verenigingen/tests/test_x.py\n"))
        self.assertIsNone(sel._SAFE_MODULE.fullmatch("verenigingen.tests.test_x\n"))
        self.assertTrue(sel._SAFE_PATH.fullmatch("verenigingen/tests/test_x.py"))

    def test_path_outside_the_app_is_ignored(self):
        self.write("scripts/testing/tests/test_elsewhere.py", TEST_SRC)
        self.assertEqual(self.pick(), [CENSUS_MOD])


class CensusFailsLoudly(SelectorCase):
    def test_dangling_census_entry_is_an_error_not_a_silent_drop(self):
        self.census.write_text(f"{CENSUS_MOD}\nverenigingen.tests.test_vanished\n")
        with self.assertRaises(sel.SelectionError):
            self.pick()

    def test_census_entry_that_lost_its_test_class_is_an_error(self):
        self.write("verenigingen/tests/test_census_one.py", HELPER_SRC)
        with self.assertRaises(sel.SelectionError):
            self.pick()

    def test_empty_or_missing_census_is_an_error(self):
        self.census.write_text("# nothing\n")
        with self.assertRaises(sel.SelectionError):
            self.pick()
        self.census.unlink()
        with self.assertRaises(sel.SelectionError):
            self.pick()

    def test_unsafe_census_line_is_refused(self):
        self.census.write_text("verenigingen.tests.test_x;rm -rf\n")
        with self.assertRaises(sel.SelectionError):
            self.pick()


class RealTree(unittest.TestCase):
    """The shipped census, against the shipped tree."""

    def test_every_census_entry_resolves_to_a_runnable_module(self):
        mods = sel.census_modules(REAL_ROOT)
        self.assertGreaterEqual(len(mods), 20)
        self.assertEqual(len(mods), len(set(mods)), "duplicate census entry")

    def test_census_keeps_the_two_modules_that_motivated_it(self):
        mods = sel.census_modules(REAL_ROOT)
        self.assertIn("verenigingen.tests.test_fixture_isolation_invariants", mods)
        self.assertIn("verenigingen.tests.integration.test_public_api_guest_access", mods)


if __name__ == "__main__":
    unittest.main()
