#!/usr/bin/env python3
"""Unit tests for scripts/validation/duplicate_helper_validator.py.

Pure-Python (no bench/site needed). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_duplicate_helper_validator.py
"""
import difflib
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


def _drift(files: dict):
    """Build a temp tree and return the --drift band: {name: (worst, best)}."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for rel, src in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src)
        return {
            f[4]: (f[6], f[3])
            for f in dhv.clone_families(str(root))
            if f[2] == 0 and f[6] >= dhv.CLONE_RATIO
        }


class DriftBandTest(unittest.TestCase):
    """`--drift` claims each family is "an edit that landed in one copy".

    It is only allowed to say that when EVERY pair is near-identical and none is
    exact. Filtering on the best pair instead of the worst made the claim nearly
    free for large families: `_make_member` has 45 copies and 990 pairs, of which
    1% reach 0.90 and the minimum similarity is 0.05 -- 45 independently written
    fixtures, printed under a header saying a fix had landed in one of them.
    """

    # 11 lines so a one-line edit is a small ratio change, not a large one.
    _BODY = "\n".join(f"    x{i} = {i}" for i in range(10))

    def _fn(self, tail):
        return f"def _helper():\n{self._BODY}\n    return {tail}\n"

    def test_a_near_identical_pair_with_no_exact_pair_is_reported(self):
        band = _drift({"a.py": self._fn("1"), "b.py": self._fn("2")})
        self.assertIn("_helper", band)

    def test_a_byte_identical_family_is_NOT_reported(self):
        """Identical copies are duplication, not drift -- nothing landed anywhere."""
        same = self._fn("1")
        self.assertEqual({}, _drift({"a.py": same, "b.py": same}))

    def test_an_unrelated_pair_is_NOT_reported(self):
        a = "def _helper():\n    return sum(range(10))\n"
        b = "def _helper():\n" + "\n".join(f"    y{i} = {i} * 3" for i in range(12)) + "\n"
        self.assertEqual({}, _drift({"a.py": a, "b.py": b}))

    def test_one_dissimilar_copy_disqualifies_the_whole_family(self):
        """The regression this filter exists for. Two copies drifted by one line,
        plus a third that is unrelated: keying on the BEST pair still reports the
        family, because the good pair carries it. Keying on the worst does not."""
        odd = "def _helper():\n" + "\n".join(f"    z{i} = {i} ** 2" for i in range(14)) + "\n"
        files = {"a.py": self._fn("1"), "b.py": self._fn("2"), "c.py": odd}

        self.assertEqual({}, _drift(files), "the unrelated third copy must disqualify it")

        # Control: the best-pair filter -- the old behaviour -- DOES report it, so
        # this test discriminates between the two aggregations rather than merely
        # passing.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel, src in files.items():
                (root / rel).write_text(src)
            by_best = [
                f[4] for f in dhv.clone_families(str(root)) if f[2] == 0 and f[3] >= dhv.CLONE_RATIO
            ]
        self.assertEqual(["_helper"], by_best)

    def test_two_unparseable_bodies_are_not_a_perfect_clone_family(self):
        """SequenceMatcher("", "").ratio() is 1.0, so two parse failures would
        otherwise be reported as a flawless drift family."""
        self.assertEqual({}, _drift({"a.py": "", "b.py": ""}))


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

    def test_methods_ARE_counted(self):
        """Inverted on 2026-08-21. This used to assert that a method is scoped by
        its class and so is not the copy-paste unit. That was wrong, and it is why
        the same defect reddened trunk twice: `_get_company_with_current_fy` lived
        in three files -- one already fixed, with a comment naming the exact error
        string -- and every copy was a METHOD, invisible to this census. So were
        the three Mollie/donation fixture helpers of #444 (#445)."""
        src = "class T:\n    def _helper(self):\n        pass\n"
        self.assertEqual({"_helper": 2}, _census({"a.py": src, "b.py": src}))

    def test_a_method_and_a_module_level_function_of_the_same_name_collide(self):
        """Deliberate: the point of the census is that a fix applied to one of them
        can be missed in the other, and that is just as true across the class
        boundary as within it."""
        as_method = "class T:\n    def _shared(self):\n        pass\n"
        as_function = "def _shared():\n    pass\n"
        self.assertEqual({"_shared": 2}, _census({"a.py": as_method, "b.py": as_function}))

    def test_a_closure_inside_a_function_is_NOT_counted(self):
        """The boundary the scan stops at. A function defined inside another
        function is scoped to that call and cannot be the copy-paste hazard this
        exists for -- and builder callbacks like `build_entry` are defined this way
        all over the payment code, so counting them would be pure noise."""
        src = "def outer():\n    def _inner():\n        pass\n    return _inner\n"
        self.assertEqual({}, _census({"a.py": src, "b.py": src}))

    def test_a_method_nested_in_a_class_in_a_function_is_NOT_counted(self):
        """Same boundary, stated for the shape the test suites actually use: a
        throwaway class defined inside a test method (a fake SDK, a probe) is local
        to that test."""
        src = "def outer():\n    class T:\n        def _inner(self):\n            pass\n    return T\n"
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


class BlockingRuleTest(unittest.TestCase):
    """What the gate FAILS on is narrower than what the census counts.

    A new copy fails only when the name is a real clone family -- at least
    CLONE_SHARE of its pairs near-identical. Blocking on the name alone fired on
    60.5% of the last 400 commits that add a Python file; this fires on 34.1%.

    Every test here builds real source files, so the similarity is measured rather
    than asserted into existence.
    """

    _BODY = "\n".join(f"    x{i} = {i}" for i in range(10))

    def _same(self, tail=0):
        """A helper whose body differs from its siblings by one token."""
        return f"def _helper():\n{self._BODY}\n    return {tail}\n"

    def _different(self, seed):
        """A helper that shares only the NAME."""
        lines = "\n".join(f"    y{seed}_{i} = {seed * i!r}" for i in range(10))
        return f"def _helper():\n{lines}\n    return {seed!r}\n"

    def _split(self, files):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel, src in files.items():
                q = root / rel
                q.parent.mkdir(parents=True, exist_ok=True)
                q.write_text(src)
            families = dhv._by_name(str(root))
            counts = {n: len(v) for n, v in families.items() if len(v) > 1}
            new = dhv.regressions(counts, {})
            blocking, advisory = dhv.split_regressions(new, families)
            return blocking, advisory, families

    def test_a_new_copy_of_a_near_identical_family_blocks(self):
        """The three Mollie fixture helpers of #444: 100% of pairs near-identical."""
        blocking, _advisory, _f = self._split(
            {"a.py": self._same(0), "b.py": self._same(1), "c.py": self._same(2)}
        )
        self.assertIn("_helper", blocking)

    def test_a_new_copy_of_a_name_collision_does_NOT_block(self):
        """45 hand-written `_make_member` fixtures are not a fix waiting to be missed."""
        files = {f"{c}.py": self._different(i) for i, c in enumerate("abcde", start=2)}
        blocking, advisory, _f = self._split(files)
        self.assertNotIn("_helper", blocking)
        self.assertIn("_helper", advisory)

    def test_the_name_collision_case_IS_reported_by_the_old_rule(self):
        """Control. Without this, the test above passes if nothing is detected at all.

        The census must still SEE the collision -- it stays in the baseline as the
        to-do list. Only the blocking decision changed.
        """
        files = {f"{c}.py": self._different(i) for i, c in enumerate("abcde", start=2)}
        _blocking, _advisory, families = self._split(files)
        counts = {n: len(v) for n, v in families.items() if len(v) > 1}
        self.assertEqual({"_helper": 5}, dhv.regressions(counts, {}))

    def test_a_near_identical_CLUSTER_blocks_even_beside_unrelated_copies(self):
        """`_persist_eur_company`: 17 copies, 50 of 136 pairs >=0.90, worst pair 0.13.

        It is the case CLAUDE.md leads with (#394: two copies fixed with a docstring
        recording why, a third missed). A rule keyed on the WORST pair calls this a
        name collision and stops blocking it -- which is why the rule is keyed on the
        SHARE of near-identical pairs instead.
        """
        files = {
            "a.py": self._same(0),
            "b.py": self._same(1),
            "c.py": self._same(2),
            "d.py": self._different(9),
        }
        blocking, _advisory, families = self._split(files)
        self.assertIn("_helper", blocking)

        # Control: the worst-pair rule would NOT have blocked it. Without this the
        # test above is satisfied by any rule at all.
        copies = families["_helper"]
        worst = min(
            difflib.SequenceMatcher(None, copies[i][2], copies[j][2]).ratio()
            for i in range(len(copies))
            for j in range(i + 1, len(copies))
        )
        self.assertLess(worst, dhv.CLONE_RATIO)

    def test_an_unparseable_body_is_not_counted_as_a_clone(self):
        """`SequenceMatcher("", "").ratio()` is 1.0, so two parse failures would
        otherwise be a flawless clone family."""
        self.assertEqual(0.0, dhv.clone_share([("a.py", "", ""), ("b.py", "", "")]))

    def test_clone_share_of_one_copy_is_zero(self):
        """No pairs at all must not be a division by zero, nor a clone family."""
        self.assertEqual(0.0, dhv.clone_share([("a.py", "x", "x")]))


class DeterminismTest(unittest.TestCase):
    """The same tree must give the same answer on every machine.

    It did not. `difflib.SequenceMatcher(None, a, b).ratio()` is asymmetric -- it
    indexes the SECOND sequence and applies autojunk to that one alone -- and
    `os.walk` yields in filesystem order, so the order copies were discovered in
    decided which way round each pair was compared. On a byte-identical tree,
    `_root` scored 0.33 locally and 0.50 in CI, and CI's whole baseline diff was
    reproducible here just by reshuffling the copies.
    """

    # These two STRADDLE the clone threshold asymmetrically: 0.8975 compared one
    # way, 0.9011 the other. So under the raw comparison the pair is a clone or
    # not depending purely on which copy was walked first -- clone_share is 0.0 one
    # way and 1.0 the other. test_the_bodies_really_are_asymmetric pins that, so
    # neither test below can quietly become a tautology.
    _A = "def _h():\n" + "\n".join(f"    v{i} = {i}" for i in range(20)) + "\n    pass\n"
    _B = ("def _h():\n" + "\n".join(f"    v{i} = {i}" for i in range(20))
          + "\n    y = '" + "a" * 46 + "'\n")

    def _bodies(self):
        """The bodies as clone_share sees them -- it is a pure function over
        normalised text, so these are used directly. Routing them through
        ast.unparse first destroys the straddle: it renormalises both to 0.9007 /
        0.9043, which are on the same side of the threshold and prove nothing."""
        return self._A, self._B

    def test_the_bodies_really_are_asymmetric(self):
        """The control. Without it the two tests below pass on any input at all --
        which is exactly what happened on the first attempt at this suite."""
        a, b = self._bodies()
        self.assertNotEqual(
            difflib.SequenceMatcher(None, a, b).ratio(),
            difflib.SequenceMatcher(None, b, a).ratio(),
        )

    def test_the_pair_ratio_is_symmetric(self):
        a, b = self._bodies()
        self.assertEqual(dhv._ratio(a, b), dhv._ratio(b, a))

    def test_clone_share_does_not_depend_on_copy_order(self):
        a, b = self._bodies()
        forward = [("a.py", "", a), ("b.py", "", b)]
        self.assertEqual(dhv.clone_share(forward), dhv.clone_share(list(reversed(forward))))

    def test_the_file_walk_is_sorted(self):
        """Deterministic order is half the fix; without it the pairing still moves."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("m.py", "a.py", "z.py"):
                (root / name).write_text("def _h():\n    return 1\n")
            (root / "sub").mkdir()
            (root / "sub" / "b.py").write_text("def _h():\n    return 1\n")
            walked = [Path(p).name for p in dhv._iter_python_files(str(root))]
            self.assertEqual(["a.py", "m.py", "z.py"], walked[:3])


class BaselineIOTest(unittest.TestCase):
    def test_a_written_baseline_reads_back_identically(self):
        counts = {"_persist_eur_company": 8, "_payment": 13}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "baseline.txt"
            dhv.write_baseline(p, counts, {})
            self.assertEqual(counts, dhv.load_baseline(p))

    def test_the_clone_family_marker_is_ignored_when_reading_back(self):
        """The marker is an inline comment. Before load_baseline stripped it, the
        count parsed as "3  # clone family, ..." and the line was silently DROPPED --
        which would have quietly un-baselined every clone family in the file."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "baseline.txt"
            p.write_text("_a::3  # clone family, 100% of pairs near-identical\n_b::2\n")
            self.assertEqual({"_a": 3, "_b": 2}, dhv.load_baseline(p))

    def test_a_baseline_written_with_families_marks_the_clone_families(self):
        with tempfile.TemporaryDirectory() as d:
            root, p = Path(d), Path(d) / "baseline.txt"
            body = "\n".join(f"    x{i} = {i}" for i in range(10))
            for i, c in enumerate("ab"):
                (root / f"{c}.py").write_text(f"def _twin():\n{body}\n    return {i}\n")
            families = dhv._by_name(str(root))
            dhv.write_baseline(p, {"_twin": 2}, families)
            self.assertIn(dhv.CLONE_MARK, p.read_text())
            self.assertEqual({"_twin": 2}, dhv.load_baseline(p))

    def test_comments_and_blanks_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "baseline.txt"
            p.write_text("# a comment\n\n_thing::4\n")
            self.assertEqual({"_thing": 4}, dhv.load_baseline(p))


class KnownGapTest(unittest.TestCase):
    """A gap #769 documents rather than fixes.

    #769's other case: `test_member_import.py::_create_stub_member_import_doc`
    is a genuine near-identical copy of a stub helper two OTHER files already
    extracted into a shared support module -- under a PUBLIC name, since a
    shared module exports its helpers without a leading underscore. census()
    groups strictly by name and never counts public names at all (see
    `WhatCountsTest.test_public_names_are_ignored` -- that exclusion exists so
    Frappe's required `execute`/`get_context`/`run_tests` don't bury the real
    signal), so a private helper left behind under its old name is compared
    against nothing: it is the only file with that name, `census()` requires
    more than one, and the byte-identical body two other files already share
    (now under a different, public name) is invisible.

    #769 chose Option 1 -- teach the CI gate to trust the near-identity
    verdict `main()` already computes, rather than rekey the whole census on
    a body fingerprint (Option 2). Option 1 does not touch `census()`/
    `_by_name()` at all, so this gap is unchanged by that fix. Closing it
    needs a fingerprint that spans BOTH private and public definitions, which
    would also rebaseline every line in duplicate_helper_baseline.txt --
    deliberately left for a follow-up, not bundled into a CI-gate fix.
    """

    _BODY = "\n".join(f"    x{i} = {i}" for i in range(10))

    def test_a_private_copy_of_an_already_extracted_public_helper_is_invisible(self):
        census = _census(
            {
                # The extracted, shared, PUBLIC copy -- excluded from the
                # census outright, by name alone, regardless of body.
                "tests/support/stubs.py": f"def make_stub():\n{self._BODY}\n",
                # A third, unextracted copy: byte-identical body, but kept
                # under its old PRIVATE name -- the one file with that name.
                "tests/test_member_import.py": f"def _make_stub():\n{self._BODY}\n",
            }
        )
        self.assertNotIn("_make_stub", census)
        self.assertNotIn("make_stub", census)


class MarkerLiteralTest(unittest.TestCase):
    """A skeptical review of #769 found that CLONE_MARK is hardcoded, as a bare
    string literal, in TWO places outside this module: the `--require-marker`
    argument `code-validation.yml` passes to `baseline_shrink_gate.py`, and
    the `grep -e '# clone family'` in that same job's "Clone-family copies did
    not grow" step. Neither can `import duplicate_helper_validator` (one is a
    subprocess argument, the other a shell pipeline), so nothing stops CLONE_MARK
    being renamed here without updating them. `baseline_shrink_gate.py` refuses
    to self-heal if the marker matches nothing on either side of a comparison
    (see its "SCOPING TO A SUBSET OF LINES" docstring section) -- but that is a
    CI-time refusal, days after the rename. This pins the literal here instead,
    so a plain unit test reddens the moment it drifts.
    """

    def test_clone_mark_matches_the_hardcoded_ci_wiring(self):
        workflow = dhv.REPO_ROOT / ".github" / "workflows" / "code-validation.yml"
        text = workflow.read_text(encoding="utf-8")
        self.assertIn(
            dhv.CLONE_MARK,
            text,
            f"CLONE_MARK is {dhv.CLONE_MARK!r} but code-validation.yml no longer "
            "contains that literal -- update its --require-marker argument (the "
            "'Baseline is in sync with the tree' step) and the grep in "
            "'Clone-family copies did not grow' to match.",
        )


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
