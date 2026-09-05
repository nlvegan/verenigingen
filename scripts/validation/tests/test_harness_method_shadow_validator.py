#!/usr/bin/env python3
"""Unit tests for scripts/validation/harness_method_shadow_validator.py.

Pure-Python (no bench/site needed). Run with:
    python -m pytest scripts/validation/tests/test_harness_method_shadow_validator.py
or plain:
    python scripts/validation/tests/test_harness_method_shadow_validator.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "harness_method_shadow_validator.py"
_spec = importlib.util.spec_from_file_location("harness_method_shadow_validator", _MOD_PATH)
hmsv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hmsv
_spec.loader.exec_module(hmsv)


def _scan(files: dict, harness_specs):
    """Build a temp tree from {relative path: source} and return hmsv.scan()."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for rel, src in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src)
        return hmsv.scan(root, harness_specs)


# A minimal harness, matching the real #194 shape: a method the harness calls on
# itself with a required argument, passed as a keyword -- every real self-call
# in enhanced_test_factory.py/utils/base.py that this session found a shadow for
# passes keywords, not bare positionals (e.g. `self.create_test_donor(donor_email=
# ..., donor_name=...)`), so the synthetic harness matches that shape rather than
# a positional call a **kwargs override could never accept regardless of intent.
_HARNESS_SRC = """
class EnhancedTestCase:
    def _ensure_company_cost_center(self, company_name):
        return company_name

    def _ensure_master_data(self):
        self._ensure_company_cost_center(company_name="Test Company")
"""

_HARNESS_SPECS = [("verenigingen/harness.py", "EnhancedTestCase")]


class PlantedShadowFiresTest(unittest.TestCase):
    """The guard's whole reason to exist: prove it actually fires on the shape
    that broke #194 (`_ensure_company_cost_center(self)` overriding
    `_ensure_company_cost_center(self, company_name)`), not merely that it stays
    quiet on the current, already-fixed tree."""

    def test_zero_arg_override_of_a_required_arg_harness_method_is_flagged(self):
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/mod/test_x.py": (
                "from verenigingen.harness import EnhancedTestCase\n"
                "class TestX(EnhancedTestCase):\n"
                "    def _ensure_company_cost_center(self):\n"
                "        pass\n"
            ),
        }
        violations = _scan(files, _HARNESS_SPECS)
        self.assertEqual(1, len(violations))
        v = violations[0]
        self.assertEqual("TestX", v.class_name)
        self.assertEqual("_ensure_company_cost_center", v.method_name)

    def test_compatible_signature_is_not_flagged(self):
        """A subclass override that accepts the same arguments the harness will
        pass is not a defect -- it may do something entirely different with
        `company_name`, but it cannot raise TypeError, and #496's own review
        scoped this guard to the certain-crash class only."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/mod/test_y.py": (
                "from verenigingen.harness import EnhancedTestCase\n"
                "class TestY(EnhancedTestCase):\n"
                "    def _ensure_company_cost_center(self, company_name):\n"
                "        return company_name.upper()\n"
            ),
        }
        self.assertEqual([], _scan(files, _HARNESS_SPECS))

    def test_kwargs_override_is_not_flagged(self):
        """A `**kwargs`-based cooperative override (the shape #496 found several
        legitimate instances of) always binds, so it is never flagged."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/mod/test_z.py": (
                "from verenigingen.harness import EnhancedTestCase\n"
                "class TestZ(EnhancedTestCase):\n"
                "    def _ensure_company_cost_center(self, **kwargs):\n"
                "        return super()._ensure_company_cost_center(**kwargs)\n"
            ),
        }
        self.assertEqual([], _scan(files, _HARNESS_SPECS))

    def test_unrelated_class_with_the_same_method_name_is_not_flagged(self):
        """A method name collision on a class that does NOT inherit the harness
        at all is not a shadow of anything -- it just happens to share a name."""
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/mod/test_w.py": (
                "class TestW:\n"
                "    def _ensure_company_cost_center(self):\n"
                "        pass\n"
            ),
        }
        self.assertEqual([], _scan(files, _HARNESS_SPECS))


class ImportAliasResolutionTest(unittest.TestCase):
    """Regression coverage for the exact ambiguity #496's own review flagged
    (and that this session's first draft of the guard reproduced): TWO
    same-named classes, `BaseTestCase`, exist in this app -- one an alias for
    `EnhancedTestCase`, one for something unrelated. A validator that matches
    class NAMES instead of following each file's actual import can attribute a
    shadow to the wrong base in either direction. These tests build that exact
    shape in miniature and require the validator to tell them apart."""

    def _tree(self):
        return {
            "verenigingen/harness.py": _HARNESS_SRC,
            # An unrelated framework base with NO connection to the harness.
            "verenigingen/other_base.py": "class OtherBase:\n    pass\n",
            # Two pure IMPORT ALIASES named identically -- neither is a `class
            # BaseTestCase(...)` definition, matching how this app's actual
            # `verenigingen/tests/test_utils.py` and
            # `verenigingen/tests/base_test_case.py` do it.
            "verenigingen/alias_good.py": (
                "from verenigingen.harness import EnhancedTestCase as BaseTestCase\n"
            ),
            "verenigingen/alias_bad.py": (
                "from verenigingen.other_base import OtherBase as BaseTestCase\n"
            ),
        }

    def test_a_class_via_the_harness_alias_is_flagged(self):
        files = self._tree()
        files["verenigingen/mod/test_real.py"] = (
            "from verenigingen.alias_good import BaseTestCase\n"
            "class TestReal(BaseTestCase):\n"
            "    def _ensure_company_cost_center(self):\n"
            "        pass\n"
        )
        violations = _scan(files, _HARNESS_SPECS)
        self.assertEqual(1, len(violations))
        self.assertEqual("TestReal", violations[0].class_name)

    def test_a_class_via_the_UNRELATED_alias_of_the_same_name_is_not_flagged(self):
        """This is the case this session's own first-draft guard got wrong: it
        matched `BaseTestCase` by name alone, found the harness-derived
        `BaseTestCase` defined elsewhere, and flagged a class that actually
        inherits a completely different base through this file's own import."""
        files = self._tree()
        files["verenigingen/mod/test_fake.py"] = (
            "from verenigingen.alias_bad import BaseTestCase\n"
            "class TestFake(BaseTestCase):\n"
            "    def _ensure_company_cost_center(self):\n"
            "        pass\n"
        )
        self.assertEqual([], _scan(files, _HARNESS_SPECS))

    def test_both_present_only_the_real_one_is_flagged(self):
        files = self._tree()
        files["verenigingen/mod/test_real.py"] = (
            "from verenigingen.alias_good import BaseTestCase\n"
            "class TestReal(BaseTestCase):\n"
            "    def _ensure_company_cost_center(self):\n"
            "        pass\n"
        )
        files["verenigingen/mod/test_fake.py"] = (
            "from verenigingen.alias_bad import BaseTestCase\n"
            "class TestFake(BaseTestCase):\n"
            "    def _ensure_company_cost_center(self):\n"
            "        pass\n"
        )
        violations = _scan(files, _HARNESS_SPECS)
        self.assertEqual(["TestReal"], [v.class_name for v in violations])


class TransitiveInheritanceTest(unittest.TestCase):
    """A subclass of a subclass of the harness must still be checked -- the real
    #496 census found shadows on intermediate framework classes
    (TransactionBoundaryTestCase, several levels deep in practice)."""

    def test_grandchild_class_is_checked(self):
        files = {
            "verenigingen/harness.py": _HARNESS_SRC,
            "verenigingen/mod/framework.py": (
                "from verenigingen.harness import EnhancedTestCase\n"
                "class MidCase(EnhancedTestCase):\n"
                "    pass\n"
            ),
            "verenigingen/mod/test_grandchild.py": (
                "from verenigingen.mod.framework import MidCase\n"
                "class TestGrandchild(MidCase):\n"
                "    def _ensure_company_cost_center(self):\n"
                "        pass\n"
            ),
        }
        violations = _scan(files, _HARNESS_SPECS)
        self.assertEqual(["TestGrandchild"], [v.class_name for v in violations])


if __name__ == "__main__":
    unittest.main()
