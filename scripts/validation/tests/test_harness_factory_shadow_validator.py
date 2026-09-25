#!/usr/bin/env python3
"""Unit tests for scripts/validation/harness_factory_shadow_validator.py.

Pure-Python (no bench/site needed). Run with:
    python -m pytest scripts/validation/tests/test_harness_factory_shadow_validator.py
or plain:
    python scripts/validation/tests/test_harness_factory_shadow_validator.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_VALIDATION_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _VALIDATION_DIR.parents[1]
sys.path.insert(0, str(_REPO_ROOT))

# Load the sibling module first under its real package name, so
# harness_factory_shadow_validator's `from scripts.validation....` import
# resolves the same module object rather than re-executing the file.
import scripts.validation.harness_super_skip_validator  # noqa: F401,E402

_MOD_PATH = _VALIDATION_DIR / "harness_factory_shadow_validator.py"
_spec = importlib.util.spec_from_file_location("harness_factory_shadow_validator", _MOD_PATH)
hfsv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hfsv
_spec.loader.exec_module(hfsv)


def _scan(files: dict):
    """Build a temp tree from {relative path: source} and return hfsv.find_violations()."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for rel, src in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src)
        return hfsv.find_violations(root=root)


# A harness base whose own setUp() shadows self.factory, mirroring
# VereningingenTestCase.setUp() (verenigingen/tests/utils/base.py:238) and
# EnhancedTestCase.setUp() (verenigingen/tests/fixtures/enhanced_test_factory.py:2471).
_HARNESS_SRC = """
class VereningingenTestCase:
    @classmethod
    def setUpClass(cls):
        pass

    @classmethod
    def tearDownClass(cls):
        pass

    def setUp(self):
        self._test_docs = []
        self.factory = object()

    def tearDown(self):
        pass
"""


class PlantedViolationFiresTest(unittest.TestCase):
    """The guard's whole reason to exist: prove it fires on the exact shape
    #1344/#1347 found -- a class that builds cls.factory in setUpClass, reads
    self.factory in a test body, and (a) never overrides setUp() at all, or
    (b) overrides setUp(), calls super().setUp(), but never re-points
    self.factory afterward."""

    def test_class_with_no_setup_override_is_flagged(self):
        files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_x.py": (
                "from verenigingen.tests.harness import VereningingenTestCase\n"
                "class TestX(VereningingenTestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        super().setUpClass()\n"
                "        cls.factory = object()\n"
                "    def test_something(self):\n"
                "        self.factory.create_test_member()\n"
            ),
        }
        violations = _scan(files)
        keys = {(v.class_name, v.attr) for v in violations}
        self.assertEqual({("TestX", "factory")}, keys)

    def test_setup_that_calls_super_but_never_repoints_is_flagged(self):
        files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_y.py": (
                "from verenigingen.tests.harness import VereningingenTestCase\n"
                "class TestY(VereningingenTestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        super().setUpClass()\n"
                "        cls.factory = object()\n"
                "    def setUp(self):\n"
                "        super().setUp()\n"
                "        self.other_thing = 1\n"
                "    def test_something(self):\n"
                "        self.factory.create_test_member()\n"
            ),
        }
        violations = _scan(files)
        keys = {(v.class_name, v.attr) for v in violations}
        self.assertEqual({("TestY", "factory")}, keys)

    def test_read_via_a_helper_method_is_also_flagged(self):
        """The read need not be in a test method body itself -- an in-class
        helper method the test calls also counts, since `_self_attr_reads`
        walks the whole class body (every method, not just test_* ones)."""
        files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_helper.py": (
                "from verenigingen.tests.harness import VereningingenTestCase\n"
                "class TestHelper(VereningingenTestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        super().setUpClass()\n"
                "        cls.factory = object()\n"
                "    def _make_member(self):\n"
                "        return self.factory.create_test_member()\n"
                "    def test_something(self):\n"
                "        self._make_member()\n"
            ),
        }
        violations = _scan(files)
        keys = {(v.class_name, v.attr) for v in violations}
        self.assertEqual({("TestHelper", "factory")}, keys)


class CompliantOverrideIsNotFlaggedTest(unittest.TestCase):
    def test_repoint_via_type_self_satisfies_the_guard(self):
        files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_ok1.py": (
                "from verenigingen.tests.harness import VereningingenTestCase\n"
                "class TestOk1(VereningingenTestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        super().setUpClass()\n"
                "        cls.factory = object()\n"
                "    def setUp(self):\n"
                "        super().setUp()\n"
                "        self.factory = type(self).factory\n"
                "    def test_something(self):\n"
                "        self.factory.create_test_member()\n"
            ),
        }
        self.assertEqual([], _scan(files))

    def test_repoint_via_dunder_class_satisfies_the_guard(self):
        """Matches test_cost_center_ui_integration.py's actual idiom:
        `self.factory = self.__class__.factory`."""
        files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_ok2.py": (
                "from verenigingen.tests.harness import VereningingenTestCase\n"
                "class TestOk2(VereningingenTestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        super().setUpClass()\n"
                "        cls.factory = object()\n"
                "    def setUp(self):\n"
                "        super().setUp()\n"
                "        self.factory = self.__class__.factory\n"
                "    def test_something(self):\n"
                "        self.factory.create_test_member()\n"
            ),
        }
        self.assertEqual([], _scan(files))

    def test_cls_factory_never_read_via_self_is_not_flagged(self):
        """Matches test_source_folder_backfill.py / test_organization_document_
        applies_on.py's shape (per #1347): cls.factory is built but no test
        body reads self.factory -- no exposure."""
        files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_unused.py": (
                "from verenigingen.tests.harness import VereningingenTestCase\n"
                "class TestUnused(VereningingenTestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        super().setUpClass()\n"
                "        cls.factory = object()\n"
                "    def test_something(self):\n"
                "        pass\n"
            ),
        }
        self.assertEqual([], _scan(files))

    def test_setup_that_skips_super_entirely_is_left_to_the_other_validator(self):
        """A setUp() override with NO super().setUp() call at all is
        harness_super_skip_validator's defect (#1307), not this one -- the
        harness's own shadowing assignment never runs in that case, so
        self.factory (unset on the instance) resolves via normal attribute
        lookup to the very same cls.factory. Flagging it here too would just
        be noise on top of the other guard's finding."""
        files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_skip.py": (
                "from verenigingen.tests.harness import VereningingenTestCase\n"
                "class TestSkip(VereningingenTestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        super().setUpClass()\n"
                "        cls.factory = object()\n"
                "    def setUp(self):\n"
                "        self.other_thing = 1\n"
                "    def test_something(self):\n"
                "        self.factory.create_test_member()\n"
            ),
        }
        self.assertEqual([], _scan(files))

    def test_non_harness_class_is_not_flagged(self):
        files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_plain.py": (
                "import unittest\n"
                "class TestPlain(unittest.TestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        cls.factory = object()\n"
                "    def test_something(self):\n"
                "        self.factory.create_test_member()\n"
            ),
        }
        self.assertEqual([], _scan(files))

    def test_class_that_never_builds_a_class_level_factory_is_not_flagged(self):
        files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_instance_only.py": (
                "from verenigingen.tests.harness import VereningingenTestCase\n"
                "class TestInstanceOnly(VereningingenTestCase):\n"
                "    def setUp(self):\n"
                "        super().setUp()\n"
                "        self.factory = object()\n"
                "    def test_something(self):\n"
                "        self.factory.create_test_member()\n"
            ),
        }
        self.assertEqual([], _scan(files))


class KnownLimitationTest(unittest.TestCase):
    """Documents a real gap instead of hiding it (see the module docstring's
    "KNOWN LIMITATION" section). `_setupclass_attrs` reads `cls.<attr> = ...`
    assignments only from the LEAF class's own `setUpClass` -- it does not
    walk the MRO the way `_is_harness_rooted` does for base resolution. A
    class-level fixture built in an INTERMEDIATE ancestor's `setUpClass`,
    inherited by a leaf that reads `self.<attr>` and never overrides
    `setUp()`, is exposed to the identical shadow (#1344/#1347's mechanism)
    but this guard finds nothing.

    Zero real instances of this shape exist in the tree today -- every
    current `cls.factory` assignment lives in the same class that reads
    `self.factory` (verified as part of the #1344/#1347 sweep). Fixing it
    would mean walking each ancestor's own `setUpClass` (in MRO order) in
    `_setupclass_attrs`, the same traversal `_is_harness_rooted` already does
    for `bases`.
    """

    def test_factory_built_in_an_intermediate_ancestor_is_not_detected(self):
        files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_intermediate.py": (
                "from verenigingen.tests.harness import VereningingenTestCase\n"
                "class _MiddleBase(VereningingenTestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        super().setUpClass()\n"
                "        cls.factory = object()\n"
                "class TestLeaf(_MiddleBase):\n"
                "    def test_something(self):\n"
                "        self.factory.create_test_member()\n"
            ),
        }
        # This SHOULD be a violation -- TestLeaf never overrides setUp(), so
        # the harness's own setUp() shadows self.factory exactly like
        # #1344/#1347 -- but the guard only reads cls.<attr> assignments in
        # the leaf's OWN setUpClass, not an ancestor's, so it finds nothing.
        violations = _scan(files)
        self.assertEqual(
            [],
            violations,
            "if this now finds something, the MRO-walking limitation "
            "described above has been fixed -- update this test (and the "
            "module docstring's KNOWN LIMITATION section) together",
        )


class RealRepoRegressionTest(unittest.TestCase):
    """Scans the actual verenigingen/ tree. With #1344/#1347's fixes applied
    this must be empty."""

    def test_no_unbaselined_violations_on_the_real_tree(self):
        violations = hfsv.find_violations()
        baseline = hfsv._load_baseline(hfsv.DEFAULT_BASELINE)
        new = [v for v in violations if v.key() not in baseline]
        self.assertEqual(
            [],
            new,
            f"New harness-factory-shadow violation(s) not in the baseline: {new}",
        )


class SelfCheckControlTest(unittest.TestCase):
    """A control for the control: mutate a known-compliant class so the
    re-point is removed, and confirm the scanner actually reddens -- proves
    it isn't vacuously passing."""

    def test_removing_the_repoint_makes_a_known_compliant_class_fail(self):
        base_files = {
            "verenigingen/tests/harness.py": _HARNESS_SRC,
            "verenigingen/tests/test_ok.py": (
                "from verenigingen.tests.harness import VereningingenTestCase\n"
                "class TestOk(VereningingenTestCase):\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        super().setUpClass()\n"
                "        cls.factory = object()\n"
                "    def setUp(self):\n"
                "        super().setUp()\n"
                "        self.factory = type(self).factory\n"
                "    def test_something(self):\n"
                "        self.factory.create_test_member()\n"
            ),
        }
        # Sanity: compliant as written.
        self.assertEqual([], _scan(base_files))

        # Now mutate away the re-point the same way a regression would.
        base_files["verenigingen/tests/test_ok.py"] = (
            "from verenigingen.tests.harness import VereningingenTestCase\n"
            "class TestOk(VereningingenTestCase):\n"
            "    @classmethod\n"
            "    def setUpClass(cls):\n"
            "        super().setUpClass()\n"
            "        cls.factory = object()\n"
            "    def setUp(self):\n"
            "        super().setUp()\n"
            "    def test_something(self):\n"
            "        self.factory.create_test_member()\n"
        )
        violations = _scan(base_files)
        self.assertEqual([("TestOk", "factory")], [(v.class_name, v.attr) for v in violations])


if __name__ == "__main__":
    unittest.main()
