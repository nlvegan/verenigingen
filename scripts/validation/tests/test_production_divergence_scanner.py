#!/usr/bin/env python3
"""Unit tests for scripts/validation/production_divergence_scanner.py (#991).

Pure-Python (no bench/site needed). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_production_divergence_scanner.py
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "production_divergence_scanner.py"
_spec = importlib.util.spec_from_file_location("production_divergence_scanner", _MOD_PATH)
pds = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pds
_spec.loader.exec_module(pds)


def _with_tree(files: dict, fn):
    tmp = tempfile.TemporaryDirectory()
    try:
        root = Path(tmp.name)
        for rel, src in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src)
        return fn(str(root))
    finally:
        tmp.cleanup()


def _census2(files: dict):
    return _with_tree(files, pds.census)


def _divergent_names(files: dict):
    return {f[4] for f in _with_tree(files, pds.divergent_families)}


class DivergenceBandTest(unittest.TestCase):
    """The core claim: at least one diverged pair is enough, unlike `--drift`
    which requires EVERY pair to be near-identical. #495's flagship family
    (`calculate_next_invoice_date`) has ten pairs and exactly one near-identical
    one -- a `--drift`-style "every pair near" rule reports nothing for it."""

    # 11 lines so a one-line edit is a small ratio change, not a large one.
    _BODY = "\n".join(f"    x{i} = {i}" for i in range(10))

    def _fn(self, name, tail):
        return f"def {name}():\n{self._BODY}\n    return {tail}\n"

    def test_one_near_pair_plus_an_unrelated_third_copy_IS_reported(self):
        """The shape --drift misses: two copies near-identical (one edited, one
        not), a third copy sharing the name but unrelated in body. This is the
        band #991 needs -- --drift's "every pair near" rule would drop this
        family entirely because of the third, dissimilar copy."""
        unrelated = "def public_fn():\n" + "\n".join(f"    z{i} = {i} ** 2" for i in range(14)) + "\n"
        files = {
            "a.py": self._fn("public_fn", "1"),
            "b.py": self._fn("public_fn", "2"),
            "c.py": unrelated,
        }
        self.assertIn("public_fn", _divergent_names(files))

        # Control: the SAME tree, scored with --drift's own stricter "every pair
        # near" selector (exact == 0 and the WORST pair >= CLONE_RATIO, i.e. near
        # must equal the pair count, not just be >= 1) reports NOTHING -- the
        # unrelated third copy drags the worst pair down to ~0. This is what
        # proves the widening in production_divergence_scanner is load-bearing
        # rather than cosmetic: the exact case this issue was filed over.
        def _strict(root):
            found = []
            for name, copies in pds._by_name(root).items():
                if len(copies) < 2:
                    continue
                exact, near, best, worst, _cos, _near_pairs = pds._pair_stats(copies)
                if exact == 0 and worst >= pds.CLONE_RATIO:
                    found.append(name)
            return found

        self.assertEqual(
            [], _with_tree(files, _strict), "the strict --drift selector must miss this shape"
        )

    def test_a_byte_identical_family_is_NOT_reported(self):
        """Identical copies are plain duplication, not divergence -- nothing has
        landed anywhere yet, so there is nothing to triage."""
        same = self._fn("public_fn", "1")
        self.assertEqual(set(), _divergent_names({"a.py": same, "b.py": same}))

    def test_an_unrelated_name_collision_is_NOT_reported(self):
        """Negative control for the worry this issue raises explicitly: production
        code has legitimate near-duplication by NAME without near-duplication by
        BODY (per-gateway handlers, interface implementations). Two totally
        different bodies sharing a public name must not be flagged."""
        a = "def public_fn():\n    return sum(range(10))\n"
        b = "def public_fn():\n" + "\n".join(f"    y{i} = {i} * 3" for i in range(12)) + "\n"
        self.assertEqual(set(), _divergent_names({"a.py": a, "b.py": b}))

    def test_cosmetic_only_difference_is_NOT_reported(self):
        """Two copies differing only in docstring/annotations are identical after
        normalising -- same carve-out as duplicate_helper_validator's --drift, and
        for the same reason: that is not behavioural drift."""
        a = 'def public_fn(x: int) -> int:\n    """Docstring A."""\n' + self._BODY + "\n    return x\n"
        b = (
            'def public_fn(x) -> int:\n    """A totally different docstring."""\n'
            + self._BODY
            + "\n    return x\n"
        )
        self.assertEqual(set(), _divergent_names({"a.py": a, "b.py": b}))


class ScopeBoundaryTest(unittest.TestCase):
    """Where this scanner's scope starts and stops -- the complement of the
    sibling gate, not an overlap with it."""

    def test_private_helpers_are_NOT_counted(self):
        """That is duplicate_helper_validator's job. Counting them here too would
        make two tools report the same finding under two different names."""
        src = "def _helper():\n    pass\n"
        self.assertEqual({}, _census2({"a.py": src, "b.py": src}))

    def test_dunder_names_are_NOT_counted(self):
        src = "def __init__(self):\n    pass\n"
        self.assertEqual({}, _census2({"a.py": src, "b.py": src}))

    def test_a_public_helper_duplicated_only_across_TEST_files_is_not_counted(self):
        """Test-file duplication is the sibling gate's job (it scans test files
        too, just restricted to underscore names). A public name repeated only in
        test files is out of THIS scanner's scope."""
        src = "def make_fixture():\n    pass\n"
        got = _census2({"tests/test_a.py": src, "tests/test_b.py": src})
        self.assertEqual({}, got)

    def test_a_test_underscore_prefixed_filename_outside_a_tests_dir_is_excluded(self):
        """146 doctype test files live next to their controller as test_*.py
        rather than under a tests/ directory. Both shapes must be excluded."""
        src = "def make_fixture():\n    pass\n"
        got = _census2({"doctype/foo/test_foo.py": src, "doctype/foo/other_test.py": src})
        self.assertEqual({}, got)

    def test_public_helper_in_one_production_file_and_one_test_file_is_not_counted(self):
        """Only production copies count toward THIS scanner's census -- a single
        production definition is not yet duplicated from this scanner's point of
        view, whatever the test suite does."""
        src = "def make_fixture():\n    pass\n"
        got = _census2({"prod.py": src, "tests/test_a.py": src})
        self.assertEqual({}, got)

    def test_a_public_function_in_two_production_files_IS_counted(self):
        src = "def calculate_thing():\n    pass\n"
        got = _census2({"a.py": src, "prod/b.py": src})
        self.assertEqual({"calculate_thing": 2}, got)

    def test_public_methods_ARE_counted(self):
        """Same reasoning as the sibling gate (#445): restricting to module-level
        functions would miss method copies, and #495's own flagship family
        includes two METHOD copies (billing_date_service.py,
        membership_dues_schedule.py)."""
        src = "class T:\n    def calculate_thing(self):\n        pass\n"
        got = _census2({"a.py": src, "b.py": src})
        self.assertEqual({"calculate_thing": 2}, got)


class DictLiteralGapTest(unittest.TestCase):
    """Documents the known, deliberate gap: a duplicated named DICT is invisible
    here by construction, because this scanner only walks FunctionDef nodes.
    #495's second family (the Biannual -> Semi-Annual map) is exactly this shape.
    This test exists so the boundary is asserted, not just described in prose."""

    def test_a_duplicated_module_level_dict_literal_is_invisible(self):
        src = (
            "_BILLING_PERIOD_TO_FREQUENCY = {\n"
            '    "Biannual": "Semi-Annual",\n'
            '    "Annual": "Annual",\n'
            "}\n"
        )
        self.assertEqual({}, _census2({"a.py": src, "b.py": src}))


class NearPairEvidenceTest(unittest.TestCase):
    """#1008: `_print_report` named the family that diverged but printed a
    truncated, alphabetically-sorted directory list (`dirs[:4]`) instead of the
    actual near-identical pair that produced the verdict -- and for a family
    with more than ~4 directories, the true pair can be truncated away
    entirely. Reproduces that exact shape: four mutually-unrelated copies
    (sorted first) plus one near-identical PAIR whose directories sort last,
    so `dirs[:4]` would show only the four unrelated ones and never mention
    the pair a human is meant to triage.
    """

    # 11 lines so a one-line edit is a small ratio change, not a large one.
    _BODY = "\n".join(f"    x{i} = {i}" for i in range(10))

    def _unrelated(self, seed):
        return "def public_fn():\n" + "\n".join(f"    q{seed}_{i} = {i} ** 2" for i in range(14)) + "\n"

    def _near(self, tail):
        return f"def public_fn():\n{self._BODY}\n    return {tail}\n"

    def _tree(self):
        return {
            "aaa_unrelated/a.py": self._unrelated(1),
            "bbb_unrelated/a.py": self._unrelated(2),
            "ccc_unrelated/a.py": self._unrelated(3),
            "ddd_unrelated/a.py": self._unrelated(4),
            # Sorts LAST alphabetically -- exactly where dirs[:4] cannot reach.
            "zzz_pair_one/a.py": self._near("1"),
            "zzz_pair_two/a.py": self._near("2"),
        }

    def test_divergent_families_reports_the_actual_near_pair_paths(self):
        result = {}

        def _capture(root):
            result["root"] = root
            return pds.divergent_families(root)

        families = {f[4]: f for f in _with_tree(self._tree(), _capture)}
        self.assertIn("public_fn", families)
        near, files, best, worst, name, dirs, near_pairs = families["public_fn"]
        self.assertEqual(6, files)
        self.assertEqual(1, near, "only the zzz_pair_one/two copies are near-identical")

        # The defect: the true pair's directories do not appear in the first
        # four of the alphabetically-sorted directory list at all.
        pair_one_dir = os.path.join(result["root"], "zzz_pair_one")
        pair_two_dir = os.path.join(result["root"], "zzz_pair_two")
        self.assertNotIn(pair_one_dir, dirs[:4])
        self.assertNotIn(pair_two_dir, dirs[:4])

        # The fix: the actual pair is named directly, regardless of where its
        # directories would fall in an alphabetical truncation.
        self.assertEqual(1, len(near_pairs))
        pair_paths = {near_pairs[0][0], near_pairs[0][1]}
        self.assertEqual(
            {
                os.path.join(result["root"], "zzz_pair_one", "a.py"),
                os.path.join(result["root"], "zzz_pair_two", "a.py"),
            },
            pair_paths,
            "the report must name the pair that produced the verdict, not a "
            "truncated, alphabetically-sorted directory list that can drop it",
        )

    def test_print_report_names_the_pair_not_just_dirs(self):
        """Integration-level check on the actual printed report: the paths of
        the diverging pair must appear in the text a human reads."""
        import contextlib
        import io

        def _run(root):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pds._print_report(root)
            return buf.getvalue()

        output = _with_tree(self._tree(), _run)
        self.assertIn("zzz_pair_one/a.py", output)
        self.assertIn("zzz_pair_two/a.py", output)


class Real495AcceptanceTest(unittest.TestCase):
    """The non-negotiable acceptance test from #991: if this does not find
    #495's family, it does not work. Run against the ACTUAL repo tree, not a
    synthetic one, because the whole point is that the real bodies are far LESS
    similar to each other than a synthetic drift example -- that is exactly what
    made --drift's "every pair near" rule the wrong selector for this case."""

    @classmethod
    def setUpClass(cls):
        cls.families = {f[4]: f for f in pds.divergent_families()}

    def test_calculate_next_invoice_date_is_found(self):
        self.assertIn(
            "calculate_next_invoice_date",
            self.families,
            "the acceptance test #991 names as non-negotiable",
        )

    def test_it_is_found_only_because_the_band_was_widened(self):
        """Proves the widening in this module's docstring is load-bearing: the
        SAME family, scored with --drift's stricter "every pair near" rule,
        is NOT reported. If this ever starts passing under the strict rule too,
        that is good news (the copies converged) -- but today it must fail,
        or the module docstring's central claim is untested."""
        near, files, best, worst, name, dirs, _near_pairs = self.families["calculate_next_invoice_date"]
        self.assertGreaterEqual(files, 5, "the six/five known current copies")
        self.assertLess(
            worst,
            pds.CLONE_RATIO,
            "worst pair must be well below CLONE_RATIO -- if the whole family "
            "were near-identical, --drift's own stricter rule would already see it",
        )
        self.assertGreaterEqual(near, 1)


if __name__ == "__main__":
    unittest.main()
