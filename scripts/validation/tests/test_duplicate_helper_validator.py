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

    def test_two_helpers_in_the_SAME_file_are_two_definitions(self):
        """Inverted by #990. This used to assert `{}` -- the census counted
        FILES, not definitions, on the theory that "a helper redefined in one
        module is a different, more obvious problem" and so didn't need
        counting. That premise did not hold: nothing else counted it either, so
        `test_rest_migration_helpers.py`'s four per-class copies of
        `_persist_eur_company` were recorded as one, and every count this tool
        produced -- including the ones gating CI -- was a floor. See
        DefinitionCountingTest for the class of fix and its negative control."""
        src = "def _a():\n    pass\n\ndef _a():\n    pass\n"
        self.assertEqual({"_a": 2}, _census({"a.py": src}))

    def test_an_unparseable_file_is_skipped_not_fatal(self):
        good = "def _shared():\n    pass\n"
        self.assertEqual(
            {}, _census({"a.py": good, "b.py": "def ( this is not python\n"})
        )


class DefinitionCountingTest(unittest.TestCase):
    """#990: the census counted FILES, not DEFINITIONS, so every figure it
    produced -- including the ones gating CI -- was a floor. Measured: a helper
    redefined on several classes in one file collapsed to a single recorded
    copy. Two independent lines of evidence: `test_rest_migration_helpers.py`
    defines `_persist_eur_company` on FOUR classes and was recorded as one
    copy, and a sibling file's own docstring counted 20 definitions where the
    tool reported 17 files -- a 3-copy gap from exactly this collapse.
    """

    def test_a_helper_redefined_on_several_classes_in_ONE_file_counts_every_definition(
        self,
    ):
        src = "\n".join(
            f"class T{i}:\n    def _shared(self):\n        pass\n" for i in range(4)
        )
        self.assertEqual({"_shared": 4}, _census({"a.py": src}))

    def test_a_genuinely_single_definition_is_counted_as_exactly_one(self):
        """Negative control. A checker that over-counts everything -- e.g. one
        that emits each definition twice, or counts a class's methods against
        the module as well as the class -- would inflate this too. Checked
        against the raw `_by_name()` map, not `census()`, because a single
        occurrence never survives census()'s ">1" filter regardless of whether
        it was counted correctly."""
        src = "def _solo():\n    pass\n"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.py").write_text(src)
            families = dhv._by_name(str(root))
        self.assertEqual(1, len(families.get("_solo", [])))

    def test_same_file_definitions_combine_with_definitions_elsewhere(self):
        """The realistic shape: some copies of a name collapsed into one file
        (per-class), others scattered across the tree -- the total must be the
        sum of both, not just whichever group is counted."""
        same_file = "\n".join(
            f"class T{i}:\n    def _shared(self):\n        pass\n" for i in range(3)
        )
        elsewhere = "def _shared():\n    pass\n"
        self.assertEqual(
            {"_shared": 4}, _census({"a.py": same_file, "b.py": elsewhere})
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

    def test_a_same_file_per_class_redefinition_can_be_a_clone_family_on_its_own(self):
        """#990: near_pairs()/clone_share() must not exempt in-file pairs. Four
        identical per-class copies of the SAME helper, all in ONE file, are
        four identical bodies and six identical pairs -- exactly the shape
        that blocks when the copies are scattered across four separate files
        (test_a_new_copy_of_a_near_identical_family_blocks, above)."""
        same_body = "\n".join(f"        x{i} = {i}" for i in range(10))
        src = "\n".join(
            f"class T{i}:\n    def _helper(self):\n{same_body}\n" for i in range(4)
        )
        blocking, _advisory, families = self._split({"a.py": src})
        self.assertEqual(4, len(families["_helper"]))
        self.assertIn("_helper", blocking)

    def test_a_trivial_helper_duplicated_in_ONE_file_is_not_a_clone_family(self):
        """#1009: sibling test classes each carrying the same one-line delegator
        carry no "a fix landed in one copy and the others were missed" risk --
        there is nothing in a one-liner to miss, and the copies are visible on one
        screen. `_run` was 10 copies of `return self.v._validate_rule(...)`."""
        src = "\n".join(
            f"class T{i}:\n    def _run(self):\n        return self.v.check()\n" for i in range(4)
        )
        blocking, _advisory, families = self._split({"a.py": src})
        self.assertEqual(4, len(families["_run"]), "all four definitions still COUNT")
        self.assertNotIn("_run", blocking, "but they must not BLOCK")

    def test_a_trivial_helper_duplicated_ACROSS_files_is_still_a_clone_family(self):
        """The same-file half of the exclusion is the load-bearing half.

        A short body can absolutely hide a divergence when the copies are far
        apart, and the counter-example is real: `_sanitize_error_message` has five
        ONE-statement copies whose divergence is in the argument list -- two pass
        `filter_sensitive_keywords=True`, two take the `False` default and never
        filter API keys or database details out of an error message. A plain size
        floor would have dropped that family from the gate.

        If this test ever goes green while the one above does too, the exclusion
        has stopped depending on file identity and the gate has quietly lost the
        `_sanitize_error_message` class."""
        body = "        return sanitize(msg, filter_keywords=True)\n"
        blocking, _advisory, families = self._split(
            {f"m{i}.py": f"def _sanitize(msg):\n{body}" for i in range(3)}
        )
        self.assertEqual(3, len(families["_sanitize"]))
        self.assertIn("_sanitize", blocking)

    def test_a_SUBSTANTIAL_helper_duplicated_in_ONE_file_is_still_a_clone_family(self):
        """The size half must not swallow real same-file clones. The motivating
        case is `_get_or_create_parent_account`: ~7 statements of account-lookup
        logic, byte-identical across five sibling classes in one file."""
        body = "\n".join(f"        step{i} = lookup({i})" for i in range(7))
        src = "\n".join(
            f"class T{i}:\n    def _helper(self):\n{body}\n" for i in range(3)
        )
        blocking, _advisory, families = self._split({"a.py": src})
        self.assertEqual(3, len(families["_helper"]))
        self.assertIn("_helper", blocking)

    def test_an_unparseable_body_is_not_counted_as_a_clone(self):
        """`SequenceMatcher("", "").ratio()` is 1.0, so two parse failures would
        otherwise be a flawless clone family."""
        self.assertEqual(0.0, dhv.clone_share([("a.py", "", ""), ("b.py", "", "")]))

    def test_clone_share_of_one_copy_is_zero(self):
        """No pairs at all must not be a division by zero, nor a clone family."""
        self.assertEqual(0.0, dhv.clone_share([("a.py", "x", "x")]))


class MonotonicityTest(unittest.TestCase):
    """#949: the blocking rule must not move the wrong way when copies change.

    The fraction rule (`near_pairs / all_pairs >= 0.25`) is not monotone in
    duplication, in EITHER direction, because the denominator grows quadratically
    while the numerator does not:

      * adding a DISSIMILAR copy can push a real clone family BELOW the threshold
        and out of the gate -- measured on develop, `_new_customer` kept its 0.93
        pair and went 33% -> 17% when a fourth unrelated copy landed;
      * removing a dissimilar copy can pull a family back IN and add its whole
        count to the tracked total -- which failed PR #922, a consolidation PR,
        for consolidating.

    An absolute count of near-identical pairs cannot move either way: adding a
    dissimilar copy leaves `near` unchanged, and removing one can only leave it
    unchanged or reduce it.
    """

    _BODY = "\n".join(f"    x{i} = {i}" for i in range(10))

    def _same(self, tail=0):
        return f"def _helper():\n{self._BODY}\n    return {tail}\n"

    def _different(self, seed):
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
            blocking, advisory = dhv.split_regressions(dhv.regressions(counts, {}), families)
            return blocking, advisory, families

    def _files(self, n_same, n_diff):
        files = {f"s{i}.py": self._same(i) for i in range(n_same)}
        files.update({f"d{i}.py": self._different(100 + i) for i in range(n_diff)})
        return files

    def test_dissimilar_copies_cannot_dilute_a_clone_family_out_of_the_gate(self):
        """Three genuine clones stay gated however many unrelated copies join them."""
        blocking, _a, families = self._split(self._files(3, 0))
        self.assertIn("_helper", blocking, "three near-identical copies must block")

        blocking, _a, families = self._split(self._files(3, 3))
        self.assertIn(
            "_helper",
            blocking,
            "the same three clones stopped blocking once unrelated copies diluted "
            "the ratio -- this is #949",
        )

        # Control: the OLD fraction rule really does drop it, so this test
        # discriminates between the two aggregations rather than merely passing.
        copies = families["_helper"]
        self.assertLess(
            dhv.clone_share(copies),
            0.25,
            "fixture is wrong: the share must fall below the old threshold, "
            "otherwise the old rule would have blocked it too and this proves nothing",
        )

    def test_removing_a_dissimilar_copy_does_not_newly_gate_a_family(self):
        """The #922 direction: consolidating must not push a family INTO the gate.

        Under the fraction rule, dropping an unrelated copy raises the share and can
        newly mark a family, adding its whole count to the tracked total -- so a
        consolidation PR fails the duplication gate. Under a count, the two states
        agree.
        """
        wide, _a, _f = self._split(self._files(3, 3))
        narrow, _a2, _f2 = self._split(self._files(3, 2))
        self.assertEqual(
            "_helper" in wide,
            "_helper" in narrow,
            "removing an unrelated copy changed the blocking decision",
        )

    def test_a_pure_name_collision_still_does_not_block(self):
        """#769's fix must survive: shared name, no near-identical pair, no block."""
        blocking, advisory, _f = self._split(self._files(0, 5))
        self.assertNotIn("_helper", blocking)
        self.assertIn("_helper", advisory, "it must still be RECORDED, just not blocked")

    def test_a_dissimilar_copy_added_WITHIN_the_same_file_cannot_dilute_a_clone_family_out(
        self,
    ):
        """#990 extends #949's guarantee to the new counting dimension: a
        dissimilar redefinition landing in the SAME file as a real clone
        family must not dilute it out of the gate, exactly as a dissimilar
        copy in a SEPARATE file must not (see the test above)."""
        body = "\n".join(f"        x{i} = {i}" for i in range(10))
        clones = "\n".join(
            f"class T{i}:\n    def _helper(self):\n{body}\n        return {i}\n"
            for i in range(3)
        )
        unrelated = (
            "class TOther:\n    def _helper(self):\n"
            + "\n".join(f"        y{i} = {i} * 3" for i in range(12))
            + "\n"
        )
        blocking, _a, families = self._split({"a.py": clones + "\n" + unrelated})
        self.assertEqual(4, len(families["_helper"]), "fixture is wrong: expected 4 defs")
        self.assertIn(
            "_helper",
            blocking,
            "three same-file clones stopped blocking once an unrelated same-file "
            "copy diluted the ratio -- this extends #949 to same-file copies",
        )


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


class NearPairEvidenceTest(unittest.TestCase):
    """#1022: `--drift`/`--report` named the family that produced a verdict but
    printed a truncated, alphabetically-sorted directory list (`dirs[:4]`)
    instead of the actual near-identical pair -- for a family with more than
    ~4 directories, the true pair's directories can sort past position 4 and
    never be printed. Same defect class as #1008, fixed in the sibling
    `production_divergence_scanner.py` by PR #1029; this reproduces the same
    shape here: four mutually-unrelated copies (sorting first, alphabetically)
    plus one near-identical PAIR whose directories sort last, so `dirs[:4]`
    structurally cannot reach either side of it.
    """

    # 11 lines so a one-line edit is a small ratio change, not a large one.
    _BODY = "\n".join(f"    x{i} = {i}" for i in range(10))

    def _unrelated(self, seed):
        return (
            "def _helper():\n"
            + "\n".join(f"    q{seed}_{i} = {i} ** 2" for i in range(14))
            + "\n"
        )

    def _near(self, tail):
        return f"def _helper():\n{self._BODY}\n    return {tail}\n"

    def _write_tree(self, root: Path) -> None:
        files = {
            "aaa_unrelated/a.py": self._unrelated(1),
            "bbb_unrelated/a.py": self._unrelated(2),
            "ccc_unrelated/a.py": self._unrelated(3),
            "ddd_unrelated/a.py": self._unrelated(4),
            # Sorts LAST alphabetically -- exactly where dirs[:4] cannot reach --
            # and neither side of the pair shares a directory with the other
            # three, so the OLD dirs[:4] output could not name either half.
            "zzz_pair_one/a.py": self._near("1"),
            "zzz_pair_two/a.py": self._near("2"),
        }
        for rel, src in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src)

    def test_clone_families_reports_the_actual_near_pair_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write_tree(root)
            families = {f[4]: f for f in dhv.clone_families(str(root))}

        self.assertIn("_helper", families)
        pairs, defs, exact, best, name, dirs, worst, cos, near_pairs = families["_helper"]
        self.assertEqual(6, defs)
        self.assertEqual(1, pairs, "only the zzz_pair_one/two copies are near-identical")

        # The defect: the true pair's directories do not appear in the first
        # four of the alphabetically-sorted directory list at all. A temp root
        # outside REPO_ROOT falls through `_rel()` to the raw absolute path
        # (see `_rel`'s docstring/behaviour), so compare against that same
        # fallback form rather than a bare repo-relative one.
        self.assertFalse(any(d.endswith("zzz_pair_one") for d in dirs[:4]))
        self.assertFalse(any(d.endswith("zzz_pair_two") for d in dirs[:4]))

        # The fix: the actual pair is named directly, regardless of where its
        # directories would fall in an alphabetical truncation.
        self.assertEqual(1, len(near_pairs))
        pair_paths = {near_pairs[0][0], near_pairs[0][1]}
        self.assertEqual(
            {
                str(root / "zzz_pair_one" / "a.py"),
                str(root / "zzz_pair_two" / "a.py"),
            },
            pair_paths,
            "the report must name the pair that produced the verdict, not a "
            "truncated, alphabetically-sorted directory list that can drop it",
        )

    def test_multiple_near_pairs_are_ALL_reported_not_just_the_best(self):
        """The reviewer on #1029 verified that fix prints EVERY pair reaching
        CLONE_RATIO, a superset guarantee stronger than "the single best pair".
        Build a family with THREE mutually near-identical copies (3 pairs) and
        confirm all three are named."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "zzz_pair_one").mkdir(parents=True)
            (root / "zzz_pair_two").mkdir(parents=True)
            (root / "zzz_pair_three").mkdir(parents=True)
            (root / "zzz_pair_one" / "a.py").write_text(self._near("1"))
            (root / "zzz_pair_two" / "a.py").write_text(self._near("2"))
            (root / "zzz_pair_three" / "a.py").write_text(self._near("3"))
            families = {f[4]: f for f in dhv.clone_families(str(root))}

        *_, near_pairs = families["_helper"]
        self.assertEqual(3, len(near_pairs), "all three pairwise combinations must be reported")

    def test_report_output_names_the_pair_not_just_dirs(self):
        """Integration-level: the actual --report print loop must emit the
        pair's paths in the text a human reads, not just directory names."""
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write_tree(root)
            families = dhv.clone_families(str(root))

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                for pairs, defs, exact, best, name, dirs, _worst, _cos, near_pairs in families:
                    print(f"{pairs:>5} {defs:>5} {exact:>5} {best:>5}  {name}")
                    dhv._print_near_pairs(near_pairs, 28)
            output = buf.getvalue()

            self.assertIn(str(root / "zzz_pair_one" / "a.py"), output)
            self.assertIn(str(root / "zzz_pair_two" / "a.py"), output)

    def test_print_near_pairs_caps_a_large_family_and_reports_the_elision(self):
        """#1045: a uniform family of N copies emits C(N,2) lines -- measured on
        this tree, `_persist_eur_company` alone contributed 150 lines from 75
        pairs, and 24 families printed more than 10 pairs each. Printing must
        stop scaling with C(N,2).

        A cap that just keeps the first N pairs (the list is sorted
        alphabetically by path, not by ratio) would be wrong evidence: it could
        keep six near-identical high-ratio pairs and silently drop the one pair
        that is barely over CLONE_RATIO, which is the more interesting fact
        about the family. So build pairs whose ratio order runs opposite their
        alphabetical order, and require BOTH extremes to survive the cap.
        """
        import contextlib
        import io
        import re

        pairs = [
            ("aaa1.py", "aaa1b.py", 0.999),
            ("bbb2.py", "bbb2b.py", 0.998),
            ("ccc3.py", "ccc3b.py", 0.997),
            ("ddd4.py", "ddd4b.py", 0.996),
            ("eee5.py", "eee5b.py", 0.995),
            ("zzz9.py", "zzz9b.py", 0.900),  # the true minimum, sorts LAST
        ]
        self.assertGreater(
            len(pairs), dhv.NEAR_PAIRS_PRINT_CAP, "the fixture must exceed the cap to matter"
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dhv._print_near_pairs(pairs, 4)
        output = buf.getvalue()

        # Fewer lines than the full cross-product: 2 lines per pair shown,
        # plus one elision line -- never all len(pairs) * 2 lines.
        printed_pair_lines = sum(1 for ln in output.splitlines() if "<->" in ln)
        self.assertLess(
            printed_pair_lines,
            len(pairs),
            "the print must stop scaling with the number of pairs",
        )

        self.assertIn("0.999", output, "the highest-ratio pair is the family's other extreme")
        self.assertIn("0.900", output, "a first-N-by-alphabetical-order cap would drop this")

        elided = len(pairs) - printed_pair_lines
        self.assertGreater(elided, 0)
        self.assertIn("elided", output.lower(), "the elision must be stated, not silent")
        self.assertIn(str(elided), output, "the elided count must be stated, not silent")

        # The elided pairs are whatever is left after the shown ones -- their
        # ratios must fall within the stated range, so a reader can tell the
        # elided pairs are not outliers hiding beyond it. Only the "<->" pair
        # lines carry a single ratio value; the elision line's "X-Y" range is
        # excluded here so it cannot masquerade as a shown pair's ratio.
        shown_ratios = {
            round(float(m), 3)
            for ln in output.splitlines()
            if "<->" in ln
            for m in re.findall(r"ratio ([\d.]+)$", ln.strip())
        }
        elided_ratios = [r for _, _, r in pairs if round(r, 3) not in shown_ratios]
        self.assertEqual(elided, len(elided_ratios))
        elision_line = next(ln for ln in output.splitlines() if "elided" in ln.lower())
        range_numbers = [float(n) for n in re.findall(r"\d+\.\d+", elision_line)]
        self.assertGreaterEqual(min(range_numbers[-2:]), min(elided_ratios) - 0.0005)
        self.assertLessEqual(max(range_numbers[-2:]), max(elided_ratios) + 0.0005)


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
