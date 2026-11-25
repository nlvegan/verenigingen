#!/usr/bin/env python3
"""Unit tests for scripts/validation/harness_super_skip_validator.py.

Pure-Python (no bench/site needed). Run with:
    python -m pytest scripts/validation/tests/test_harness_super_skip_validator.py
or plain:
    python scripts/validation/tests/test_harness_super_skip_validator.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "harness_super_skip_validator.py"
_spec = importlib.util.spec_from_file_location("harness_super_skip_validator", _MOD_PATH)
hssv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hssv
_spec.loader.exec_module(hssv)


def _scan(files: dict):
    """Build a temp tree from {relative path: source} and return hssv.find_violations()."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for rel, src in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src)
        return hssv.find_violations(root=root)


_HARNESS_SRC = """
class VereningingenTestCase:
    settings_company = None

    @classmethod
    def setUpClass(cls):
        cls._track_created_docs = []

    @classmethod
    def tearDownClass(cls):
        pass

    def setUp(self):
        self._test_docs = []

    def tearDown(self):
        pass
"""


class PlantedViolationFiresTest(unittest.TestCase):
    """The guard's whole reason to exist: prove it fires on the exact shape
    #1307 found (a direct VereningingenTestCase subclass defining setUp/
    tearDown with no super() call at all), not merely that it stays quiet on
    the current, already-fixed tree."""

    def test_direct_subclass_skipping_super_in_setup_and_teardown_is_flagged(self):
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_x.py": (
                "from verenigingen.harness import VereningingenTestCase\n"
                "class TestX(VereningingenTestCase):\n"
                "    def setUp(self):\n"
                "        self.original_user = None\n"
                "    def tearDown(self):\n"
                "        pass\n"
            ),
        }
        violations = _scan(files)
        keys = {(v.class_name, v.method) for v in violations}
        self.assertEqual({("TestX", "setUp"), ("TestX", "tearDown")}, keys)

    def test_indirect_subclass_via_a_local_mixin_is_also_flagged(self):
        """The chain TestY -> _SomeMixin -> VereningingenTestCase must resolve
        transitively, not just a direct base."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_y.py": (
                "from verenigingen.harness import VereningingenTestCase\n"
                "class _SomeMixin(VereningingenTestCase):\n"
                "    pass\n"
                "class TestY(_SomeMixin):\n"
                "    def setUp(self):\n"
                "        pass\n"
            ),
        }
        violations = _scan(files)
        keys = {(v.class_name, v.method) for v in violations}
        self.assertEqual({("TestY", "setUp")}, keys)

    def test_setupclass_and_teardownclass_skipping_super_are_flagged_independently(self):
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_z.py": (
                "from verenigingen.harness import VereningingenTestCase\n"
                "class TestZ(VereningingenTestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        cls.factory = object()\n"
                "    @classmethod\n"
                "    def tearDownClass(cls):\n"
                "        pass\n"
            ),
        }
        violations = _scan(files)
        keys = {(v.class_name, v.method) for v in violations}
        self.assertEqual({("TestZ", "setUpClass"), ("TestZ", "tearDownClass")}, keys)


class CompliantOverrideIsNotFlaggedTest(unittest.TestCase):
    def test_super_call_anywhere_in_the_body_satisfies_the_guard(self):
        """super().setUp() need not be the first statement -- the guard checks
        presence, not position, matching the repo's actual convention (own
        logic first in tearDown, super() called last)."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_ok.py": (
                "from verenigingen.harness import VereningingenTestCase\n"
                "class TestOk(VereningingenTestCase):\n"
                "    def setUp(self):\n"
                "        super().setUp()\n"
                "        self.original_user = None\n"
                "    def tearDown(self):\n"
                "        self.original_user = None\n"
                "        super().tearDown()\n"
            ),
        }
        self.assertEqual([], _scan(files))

    def test_class_that_never_overrides_the_method_is_not_flagged(self):
        """Normal MRO dispatch already calls the harness version; nothing to
        skip, so nothing to flag."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_inherits.py": (
                "from verenigingen.harness import VereningingenTestCase\n"
                "class TestInherits(VereningingenTestCase):\n"
                "    def test_something(self):\n"
                "        pass\n"
            ),
        }
        self.assertEqual([], _scan(files))

    def test_non_harness_class_skipping_super_is_not_flagged(self):
        """A bare unittest.TestCase/FrappeTestCase subclass has no per-test
        contract to skip -- only VereningingenTestCase/EnhancedTestCase-rooted
        classes carry the isolation logic this guard protects."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_plain.py": (
                "import unittest\n"
                "class TestPlain(unittest.TestCase):\n"
                "    def setUp(self):\n"
                "        pass\n"
            ),
        }
        self.assertEqual([], _scan(files))


class ExplicitBaseCallTest(unittest.TestCase):
    """#1348 gap 1: ``Base.setUp(self)`` is an honoured contract, not a skip --
    but only when Base is really a base of the class and the method name matches."""

    def _violations(self, body: str, extra: str = "", bases: str = "EnhancedTestCase"):
        # Realistic layout: the harness sits under a SCANNED path and extends
        # ErrorLogGuardMixin + a FrappeTestCase-like base, as the real one does.
        files = {
            "verenigingen/tests/fixtures/enhanced_test_factory.py": (
                "class ErrorLogGuardMixin:\n    def setUp(self):\n        pass\n"
                "class FrappeTestCase:\n    def setUp(self):\n        pass\n"
                "class EnhancedTestCase(ErrorLogGuardMixin, FrappeTestCase):\n"
                "    def setUp(self):\n        self._test_docs = []\n"
            ),
            "verenigingen/tests/test_e.py": (
                "from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase\n"
                + extra
                + f"class TestE({bases}):\n"
                + body
            ),
        }
        return sorted((v.class_name, v.method) for v in _scan(files))

    def test_explicit_harness_base_call_is_not_flagged(self):
        self.assertEqual([], self._violations("    def setUp(self):\n        EnhancedTestCase.setUp(self)\n"))

    def test_explicit_call_to_an_intermediate_base_is_not_flagged(self):
        extra = "class _Mid(EnhancedTestCase):\n    pass\n"
        body = "    def tearDown(self):\n        _Mid.tearDown(self)\n"
        self.assertEqual([], self._violations(body, extra, bases="_Mid"))

    def test_explicit_classmethod_base_call_is_not_flagged(self):
        body = (
            "    @classmethod\n    def setUpClass(cls):\n        EnhancedTestCase.setUpClass()\n"
        )
        self.assertEqual([], self._violations(body))

    def test_explicit_call_to_a_harness_rooted_grandparent_is_not_flagged(self):
        """Pins transitive ancestry: the callee is two levels up, not a direct base."""
        extra = "class _Mid(EnhancedTestCase):\n    pass\nclass _Low(_Mid):\n    pass\n"
        body = "    def setUp(self):\n        EnhancedTestCase.setUp(self)\n"
        self.assertEqual([], self._violations(body, extra, bases="_Low"))

    def test_control_explicit_call_to_non_harness_ancestor_is_still_flagged(self):
        """FrappeTestCase/ErrorLogGuardMixin are ancestors of the harness but
        calling them directly skips the harness setUp (the #1307 defect)."""
        for callee in ("FrappeTestCase", "ErrorLogGuardMixin"):
            with self.subTest(callee=callee):
                body = f"    def setUp(self):\n        {callee}.setUp(self)\n"
                self.assertEqual([("TestE", "setUp")], self._violations(body))

    def test_control_classmethod_base_call_with_cls_argument_is_still_flagged(self):
        """``Base.setUpClass(cls)`` raises TypeError at runtime; only the
        zero-argument form is accepted."""
        body = "    @classmethod\n    def setUpClass(cls):\n        EnhancedTestCase.setUpClass(cls)\n"
        self.assertEqual([("TestE", "setUpClass")], self._violations(body))

    def test_control_unrelated_class_call_is_still_flagged(self):
        extra = "class Unrelated:\n    def setUp(self):\n        pass\n"
        body = "    def setUp(self):\n        Unrelated.setUp(self)\n"
        self.assertEqual([("TestE", "setUp")], self._violations(body, extra))

    def test_control_other_lifecycle_method_on_base_is_still_flagged(self):
        body = "    def setUp(self):\n        EnhancedTestCase.tearDown(self)\n"
        self.assertEqual([("TestE", "setUp")], self._violations(body))

    def test_control_base_call_without_self_is_still_flagged(self):
        body = "    def setUp(self):\n        EnhancedTestCase.setUp(object())\n"
        self.assertEqual([("TestE", "setUp")], self._violations(body))

    def test_control_no_call_at_all_is_still_flagged(self):
        self.assertEqual([("TestE", "setUp")], self._violations("    def setUp(self):\n        pass\n"))


class MixinAheadOfHarnessBaseTest(unittest.TestCase):
    """#1348 gap 2: a non-harness mixin listed ahead of the harness base whose
    lifecycle method skips super() starves the harness method."""

    _MIXIN_FILE = "verenigingen/tests/mixins.py"

    def _violations(self, mixin_body, bases="_Mixin, VereningingenTestCase", mixin_file=None):
        mixin_src = "class _Mixin:\n" + mixin_body
        use = "class TestM(" + bases + "):\n    def test_a(self):\n        pass\n"
        files = {"verenigingen/harness.py": _HARNESS_SRC}
        if mixin_file is None:
            files["verenigingen/tests/test_m.py"] = mixin_src + use
        else:
            files[mixin_file] = mixin_src
            files["verenigingen/tests/test_m.py"] = use
        return sorted((v.class_name, v.method) for v in _scan(files))

    _SKIP = "    def setUp(self):\n        self.x = 1\n"

    def test_skipping_mixin_ahead_of_harness_base_is_flagged(self):
        self.assertEqual([("_Mixin", "setUp")], self._violations(self._SKIP))

    def test_every_lifecycle_method_is_covered(self):
        body = (
            "    def tearDown(self):\n        pass\n"
            "    @classmethod\n    def setUpClass(cls):\n        pass\n"
            "    @classmethod\n    def tearDownClass(cls):\n        pass\n"
        )
        self.assertEqual(
            [("_Mixin", "setUpClass"), ("_Mixin", "tearDown"), ("_Mixin", "tearDownClass")],
            self._violations(body),
        )

    def test_mixin_defined_in_another_module_is_resolved_by_name(self):
        """Resolution is by class name across the tree (not import aware)."""
        self.assertEqual(
            [("_Mixin", "setUp")],
            self._violations(self._SKIP, mixin_file=self._MIXIN_FILE),
        )

    def test_control_same_mixin_after_the_harness_base_is_not_flagged(self):
        self.assertEqual([], self._violations(self._SKIP, bases="VereningingenTestCase, _Mixin"))

    def test_control_mixin_ahead_calling_super_is_not_flagged(self):
        body = "    def setUp(self):\n        super().setUp()\n"
        self.assertEqual([], self._violations(body))

    def test_control_mixin_ahead_calling_harness_base_explicitly_is_not_flagged(self):
        body = "    def setUp(self):\n        VereningingenTestCase.setUp(self)\n"
        self.assertEqual([], self._violations(body))

    def test_control_mixin_ahead_without_lifecycle_method_is_not_flagged(self):
        body = "    def helper(self):\n        pass\n"
        self.assertEqual([], self._violations(body))

    def test_control_mixin_ahead_of_non_harness_base_is_not_flagged(self):
        """The harness roots' own shape: ErrorLogGuardMixin ahead of FrappeTestCase."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "class FrappeTestCase:\n    pass\n"
                "class _Mixin:\n" + self._SKIP
                + "class EnhancedTestCase(_Mixin, FrappeTestCase):\n    pass\n"
            ),
        }
        self.assertEqual([], _scan(files))

    def test_mixin_ahead_of_a_harness_rooted_intermediate_is_flagged(self):
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "class _Mixin:\n" + self._SKIP
                + "class _Mid(VereningingenTestCase):\n    pass\n"
                "class TestM(_Mixin, _Mid):\n    pass\n"
            ),
        }
        self.assertEqual([("_Mixin", "setUp")], sorted((v.class_name, v.method) for v in _scan(files)))

    def test_skipping_mixin_second_in_bases_but_still_ahead_is_flagged(self):
        """Not only bases[0]: an inert first mixin must not hide a skipping second one."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "class _Inert:\n    pass\n"
                "class _Mixin:\n" + self._SKIP
                + "class TestM(_Inert, _Mixin, VereningingenTestCase):\n    pass\n"
            ),
        }
        self.assertEqual([("_Mixin", "setUp")], sorted((v.class_name, v.method) for v in _scan(files)))

    def test_mixin_calling_a_harness_class_that_is_not_its_ancestor_is_flagged(self):
        """Explicit call to a harness-rooted Z that is not a base of the using class does not count."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "class _Z(VereningingenTestCase):\n    pass\n"
                "class _Mixin:\n    def setUp(self):\n        _Z.setUp(self)\n"
                "class TestM(_Mixin, VereningingenTestCase):\n    pass\n"
            ),
        }
        self.assertEqual([("_Mixin", "setUp")], sorted((v.class_name, v.method) for v in _scan(files)))

    def test_mixin_between_two_harness_bases_is_flagged(self):
        """'Ahead of a harness base' means ahead of the LAST one, not the first."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "class _A(VereningingenTestCase):\n    pass\n"
                "class _B(VereningingenTestCase):\n    pass\n"
                "class _Mixin:\n" + self._SKIP
                + "class TestM(_A, _Mixin, _B):\n    pass\n"
            ),
        }
        self.assertEqual([("_Mixin", "setUp")], sorted((v.class_name, v.method) for v in _scan(files)))

    def test_harness_rooted_skipping_mixin_is_reported_once_by_the_main_rule(self):
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "class _Mix(VereningingenTestCase):\n" + self._SKIP
                + "class _Other(VereningingenTestCase):\n    pass\n"
                "class TestM(_Mix, _Other):\n    pass\n"
            ),
        }
        found = _scan(files)
        self.assertEqual([("_Mix", "setUp")], [(v.class_name, v.method) for v in found])
        self.assertEqual("", found[0].ahead_of, "main rule, not the ordering rule, must report it")

    def test_mixin_used_by_two_classes_is_reported_once(self):
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "class _Mixin:\n" + self._SKIP
                + "class A(_Mixin, VereningingenTestCase):\n    pass\n"
                "class B(_Mixin, VereningingenTestCase):\n    pass\n"
            ),
        }
        self.assertEqual(1, len(_scan(files)))


class NextClassInMroTest(unittest.TestCase):
    """#2939: an explicit base call must reach the NEXT class in the MRO that
    defines the method, not merely some harness-rooted ancestor."""

    def _violations(self, mix_body: str, other_body: str, bases: str = "Mix, Other"):
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "from verenigingen.harness import VereningingenTestCase\n"
                "class Mix(VereningingenTestCase):\n" + mix_body + "\n"
                "class Other(VereningingenTestCase):\n" + other_body + "\n"
                f"class T({bases}):\n    def test_it(self):\n        pass\n"
            ),
        }
        return sorted((v.class_name, v.method, v.via) for v in _scan(files))

    _OTHER = "    def setUp(self):\n        super().setUp()\n"
    _MIX_SKIPS = "    def setUp(self):\n        VereningingenTestCase.setUp(self)\n"

    def test_call_that_jumps_over_a_sibling_definer_is_flagged(self):
        """Mix passes alone (#1348) but in T(Mix, Other) skips Other.setUp."""
        self.assertEqual([("Mix", "setUp", "T")], self._violations(self._MIX_SKIPS, self._OTHER))

    def test_the_jump_is_flagged_for_class_level_hooks_too(self):
        mix = "    @classmethod\n    def setUpClass(cls):\n        VereningingenTestCase.setUpClass()\n"
        other = "    @classmethod\n    def setUpClass(cls):\n        super().setUpClass()\n"
        self.assertEqual([("Mix", "setUpClass", "T")], self._violations(mix, other))

    def test_control_call_to_a_defining_intermediate_that_is_next_passes(self):
        """Correct explicit call: Low's next definer is Mid, and it calls Mid."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "from verenigingen.harness import VereningingenTestCase\n"
                "class Mid(VereningingenTestCase):\n    def setUp(self):\n        super().setUp()\n"
                "class Low(Mid):\n    def setUp(self):\n        Mid.setUp(self)\n"
            ),
        }
        self.assertEqual([], _scan(files))

    def test_control_call_over_a_defining_intermediate_is_flagged(self):
        """Same shape, but Low jumps over Mid to the root: Mid.setUp is skipped
        in single inheritance too, which the pre-#2939 ancestry rule accepted."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "from verenigingen.harness import VereningingenTestCase\n"
                "class Mid(VereningingenTestCase):\n    def setUp(self):\n        super().setUp()\n"
                "class Low(Mid):\n    def setUp(self):\n        VereningingenTestCase.setUp(self)\n"
            ),
        }
        self.assertEqual([("Low", "setUp")], [(v.class_name, v.method) for v in _scan(files)])

    def test_control_sibling_defining_no_setup_is_not_skipped(self):
        self.assertEqual([], self._violations(self._MIX_SKIPS, "    pass\n"))

    def test_a_call_the_main_rule_flags_is_reported_once_not_twice(self):
        """Dedup test. Stranger is harness-rooted, defines setUp, and is NOT an
        ancestor of Mix, so the main rule flags ``Stranger.setUp(self)``. The
        skipped-sibling pass also flags it (Stranger is not Other, the next
        definer in T(Mix, Other)); the same key must be reported exactly once."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_m.py": (
                "from verenigingen.harness import VereningingenTestCase\n"
                "class Stranger(VereningingenTestCase):\n    def setUp(self):\n        super().setUp()\n"
                "class Mix(VereningingenTestCase):\n    def setUp(self):\n        Stranger.setUp(self)\n"
                "class Other(VereningingenTestCase):\n    def setUp(self):\n        super().setUp()\n"
                "class T(Mix, Other):\n    pass\n"
            ),
        }
        self.assertEqual([("Mix", "setUp")], [(v.class_name, v.method) for v in _scan(files)])

    def test_control_mixin_used_alone_still_passes(self):
        self.assertEqual([], self._violations(self._MIX_SKIPS, self._OTHER, bases="Mix"))

    def test_control_sibling_ordered_before_the_mixin_is_not_skipped(self):
        """T(Other, Mix): Other.setUp runs first via super() into Mix, whose
        call to the harness root skips nothing."""
        self.assertEqual([], self._violations(self._MIX_SKIPS, self._OTHER, bases="Other, Mix"))

    def test_control_cooperative_super_in_the_mixin_passes(self):
        mix = "    def setUp(self):\n        super().setUp()\n"
        self.assertEqual([], self._violations(mix, self._OTHER))


class RealRepoRegressionTest(unittest.TestCase):
    """Scans the actual verenigingen/ tree. With #1307's fix applied this
    must be empty; before the fix (see git history of the three files it
    names) it found exactly 10 (4 + 4 + 2 lifecycle-method violations across
    the three classes the issue named)."""

    def test_no_unbaselined_violations_on_the_real_tree(self):
        violations = hssv.find_violations()
        baseline = hssv._load_baseline(hssv.DEFAULT_BASELINE)
        new = [v for v in violations if v.key() not in baseline]
        self.assertEqual(
            [],
            new,
            f"New harness-super-skip violation(s) not in the baseline: {new}",
        )


class SelfCheckControlTest(unittest.TestCase):
    """A control for the control: mutate the real validator so it can no
    longer see a super() call, and confirm the RealRepoRegressionTest-style
    scan actually reddens -- proves the scanner isn't vacuously passing."""

    def test_mutating_super_call_detection_makes_a_known_compliant_class_fail(self):
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_ok.py": (
                "from verenigingen.harness import VereningingenTestCase\n"
                "class TestOk(VereningingenTestCase):\n"
                "    def setUp(self):\n"
                "        super().setUp()\n"
            ),
        }
        # Sanity: compliant as written.
        self.assertEqual([], _scan(files))

        # Now mutate away the super() call the same way a regression would.
        files["verenigingen/tests/test_ok.py"] = (
            "from verenigingen.harness import VereningingenTestCase\n"
            "class TestOk(VereningingenTestCase):\n"
            "    def setUp(self):\n"
            "        pass\n"
        )
        violations = _scan(files)
        self.assertEqual([("TestOk", "setUp")], [(v.class_name, v.method) for v in violations])


if __name__ == "__main__":
    unittest.main()
