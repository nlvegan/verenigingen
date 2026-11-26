#!/usr/bin/env python3
"""Unit tests for scripts/validation/archived/doctype_field_validator.py (#2934).

The `doctype-field-validator` pre-commit hook runs this validator with `--reduced-fp-mode`.
Its `query_aliases` / `test_patterns` exclusions were assigned after the `return` of
`_convert_doctypes_for_compatibility`, so they never existed and `--reduced-fp-mode` excluded
nothing beyond the always-on sets. These tests pin the exclusions on the object the hook builds.

Stdlib only; the validator is loaded from the repo by path, so it is the real one.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

_VALIDATION = Path(__file__).resolve().parents[1]
_MODULE = _VALIDATION / "archived" / "doctype_field_validator.py"

_QUERY_ALIASES = {"membership", "invoice", "amount", "currency"}  # not "status": always-on already
_TEST_PATTERNS = {"old_rate", "new_rate", "end_date", "state", "doc_status"}


def _load_archived_validator_module():
    import sys

    sys.path.insert(0, str(_VALIDATION))  # the module imports doctype_loader from here
    spec = importlib.util.spec_from_file_location("archived_doctype_field_validator_2934", _MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReducedFpExclusionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        # An empty app dir: the loader finds no doctypes, which is enough to build the object.
        app = Path(cls._tmp.name) / "bench" / "apps" / "verenigingen"
        app.mkdir(parents=True)
        module = _load_archived_validator_module()
        cls.validator = module.AccurateFieldValidator(str(app))

    def setUp(self):
        self.validator.reduced_fp_mode = False

    def test_both_exclusion_sets_exist_with_their_names(self):
        # RED on develop: neither key exists (statements sat after a `return`).
        excluded = self.validator.excluded_patterns
        self.assertTrue(_QUERY_ALIASES <= excluded.get("query_aliases", set()), excluded.keys())
        self.assertTrue(_TEST_PATTERNS <= excluded.get("test_patterns", set()), excluded.keys())

    def test_reduced_fp_mode_excludes_a_query_alias_and_a_test_name(self):
        # RED on develop: is_excluded_pattern falls through and returns False.
        self.validator.enable_reduced_fp_mode()
        for name in ("amount", "end_date"):
            with self.subTest(name=name):
                self.assertTrue(self.validator.is_excluded_pattern("member", name, f"x = member.{name}"))

    def test_without_reduced_fp_mode_the_same_names_are_not_excluded(self):
        # Control: the names are excluded by the mode, not unconditionally, and an unrelated
        # field name is never excluded in either mode (so the True above is not always-True).
        for name in ("amount", "end_date"):
            with self.subTest(name=name):
                self.assertFalse(self.validator.is_excluded_pattern("member", name, f"x = member.{name}"))
        self.validator.enable_reduced_fp_mode()
        self.assertFalse(
            self.validator.is_excluded_pattern("member", "zzz_no_such_field", "x = member.zzz_no_such_field")
        )


if __name__ == "__main__":
    unittest.main()
