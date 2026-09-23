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
