#!/usr/bin/env python3
"""Tests for scripts/validation/reimported_testcase_validator.py (#1939).

Stdlib only. Synthetic trees prove the validator catches each binding form and does NOT
flag the legitimate shapes (controls); the last test asserts the real tree is clean, which
is the guard that fails CI if a re-collecting import is ever added.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reimported_testcase_validator as v  # noqa: E402

DONOR = '''
import unittest
class Base(unittest.TestCase):
    def test_inherited(self): pass
class TestFoo(unittest.TestCase):
    def test_a(self): pass
class TestViaBase(Base):
    pass
class NoTests(unittest.TestCase):
    def helper(self): pass
class PlainTestThing:
    def test_a(self): pass
'''


def _scan(importer_src):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "test_donor.py").write_text(DONOR)
        (pkg / "test_importer.py").write_text(importer_src)
        return [(rel.name, bound, target) for rel, _l, bound, target in v.scan(root) if rel.name == "test_importer.py"]


class ReimportedTestCaseTests(unittest.TestCase):
    def test_from_import_is_caught(self):
        got = _scan("from pkg.test_donor import TestFoo\n")
        self.assertEqual(got, [("test_importer.py", "TestFoo", "pkg.test_donor.TestFoo")])

    def test_aliased_import_is_caught(self):
        self.assertEqual(len(_scan("from pkg.test_donor import TestFoo as Other\n")), 1)

    def test_relative_import_is_caught(self):
        self.assertEqual(len(_scan("from .test_donor import TestFoo\n")), 1)

    def test_star_import_is_caught_for_every_runnable_class(self):
        got = {t for _f, _b, t in _scan("from pkg.test_donor import *\n")}
        self.assertEqual(got, {"pkg.test_donor.Base", "pkg.test_donor.TestFoo", "pkg.test_donor.TestViaBase"})

    def test_class_whose_tests_are_inherited_is_caught(self):
        self.assertEqual(len(_scan("from pkg.test_donor import TestViaBase\n")), 1)

    def test_import_inside_try_is_caught(self):
        self.assertEqual(len(_scan("try:\n    from pkg.test_donor import TestFoo\nexcept ImportError:\n    TestFoo = None\n")), 1)

    def test_module_attribute_assignment_is_caught(self):
        got = _scan("from pkg import test_donor\nX = test_donor.TestFoo\n")
        self.assertEqual(got, [("test_importer.py", "X", "pkg.test_donor.TestFoo")])

    def test_assignment_alias_of_an_imported_class_is_caught(self):
        # the import is flagged too; the alias is a second binding of the same class
        self.assertEqual(len(_scan("from pkg.test_donor import TestFoo\nAlias = TestFoo\n")), 2)

    # ---- controls: shapes that must NOT be flagged ----
    def test_testcase_without_test_methods_is_not_flagged(self):
        self.assertEqual(_scan("from pkg.test_donor import NoTests\n"), [])

    def test_plain_class_is_not_flagged(self):
        self.assertEqual(_scan("from pkg.test_donor import PlainTestThing\n"), [])

    def test_module_import_and_attribute_use_is_not_flagged(self):
        src = "from pkg import test_donor\n\ndef f():\n    return test_donor.TestFoo\n"
        self.assertEqual(_scan(src), [])

    def test_type_checking_import_is_not_flagged_but_runtime_else_is(self):
        self.assertEqual(_scan("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pkg.test_donor import TestFoo\n"), [])
        self.assertEqual(
            len(_scan("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    pass\nelse:\n    from pkg.test_donor import TestFoo\n")), 1
        )

    def test_import_inside_a_function_is_not_flagged(self):
        src = "def f():\n    from pkg.test_donor import TestFoo\n    return TestFoo\n"
        self.assertEqual(_scan(src), [])

    def test_file_not_named_test_star_is_out_of_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            (root / "pkg" / "test_donor.py").write_text(DONOR)
            (root / "pkg" / "runner.py").write_text("from pkg.test_donor import TestFoo\n")
            self.assertEqual(v.scan(root), [])

    def test_the_real_tree_is_clean(self):
        root = Path(__file__).resolve().parents[3]
        self.assertTrue((root / "verenigingen").is_dir(), "root resolution is wrong")
        self.assertEqual(v.scan(root), [])


if __name__ == "__main__":
    unittest.main()
