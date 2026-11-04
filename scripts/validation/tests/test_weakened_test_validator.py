#!/usr/bin/env python3
"""Unit tests for scripts/validation/weakened_test_validator.py (#2061).

Pure-Python (no bench/site). Run with:
    python -m unittest discover -s scripts/validation/tests -p 'test_weakened_test_validator.py'
"""
import importlib.util
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "weakened_test_validator.py"
_spec = importlib.util.spec_from_file_location("weakened_test_validator", _MOD_PATH)
wtv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = wtv
_spec.loader.exec_module(wtv)


def src(s):
    return textwrap.dedent(s).lstrip("\n")


def run(base, head, base_prod=None, head_prod=None):
    return wtv.compare(base, head, base_prod or {}, head_prod or {})


def names(items):
    return sorted(i.test for i in items)


THREE_ASSERTS = src(
    """
    class TestA(Base):
        def test_x(self):
            self.assertEqual(1, f())
            self.assertTrue(g())
            self.assertIn("a", h())
    """
)


class TestRemoved(unittest.TestCase):
    def test_deleted_test_is_reported(self):
        base = {"t/test_a.py": THREE_ASSERTS + "    def test_y(self):\n        self.assertTrue(k())\n"}
        head = {"t/test_a.py": THREE_ASSERTS}
        r = run(base, head)
        self.assertEqual(names(r.removed), ["TestA.test_y"])

    def test_commented_out_test_is_reported_as_commented(self):
        base = {"t/test_a.py": THREE_ASSERTS}
        head = {"t/test_a.py": "class TestA(Base):\n    pass\n    # def test_x(self):\n    #     pass\n"}
        r = run(base, head)
        self.assertEqual(names(r.removed), ["TestA.test_x"])
        self.assertTrue(r.removed[0].commented_out)

    def test_control_moved_test_to_other_file_is_not_reported(self):
        base = {"t/test_a.py": THREE_ASSERTS}
        head = {"t/test_a.py": "", "t/test_b.py": THREE_ASSERTS.replace("TestA", "TestB")}
        r = run(base, head)
        self.assertEqual(r.removed, [])
        self.assertEqual(r.assertions_removed, [])

    def test_control_renamed_test_is_paired_not_removed(self):
        base = {"t/test_a.py": THREE_ASSERTS}
        head = {"t/test_a.py": THREE_ASSERTS.replace("test_x", "test_x_renamed")}
        r = run(base, head)
        self.assertEqual(r.removed, [])

    def test_renamed_test_that_lost_assertions_is_still_caught(self):
        base = {"t/test_a.py": THREE_ASSERTS}
        head = {
            "t/test_a.py": src(
                """
                class TestA(Base):
                    def test_x_renamed(self):
                        self.assertEqual(1, f())
                """
            )
        }
        r = run(base, head)
        self.assertEqual(r.removed, [])
        self.assertEqual(names(r.assertions_removed), ["TestA.test_x_renamed"])

    def test_deleted_with_the_code_it_tests_is_cleanup(self):
        base = {"t/test_a.py": src(
            """
            class TestA(Base):
                def test_legacy(self):
                    self.assertTrue(legacy_widget_builder())
            """
        )}
        head = {"t/test_a.py": "class TestA(Base):\n    pass\n"}
        base_prod = {"app/w.py": "def legacy_widget_builder():\n    return 1\n"}
        r = run(base, head, base_prod, {"app/w.py": ""})
        self.assertEqual(r.removed, [])
        self.assertEqual(names(r.removed_cleanup), ["TestA.test_legacy"])

    def test_control_deleted_test_whose_code_still_exists_is_not_cleanup(self):
        base = {"t/test_a.py": src(
            """
            class TestA(Base):
                def test_live(self):
                    self.assertTrue(live_widget_builder())
            """
        )}
        head = {"t/test_a.py": "class TestA(Base):\n    pass\n"}
        prod = {"app/w.py": "def live_widget_builder():\n    return 1\n"}
        r = run(base, head, prod, prod)
        self.assertEqual(names(r.removed), ["TestA.test_live"])
        self.assertEqual(r.removed_cleanup, [])

    def test_control_moved_and_rewritten_test_is_paired_by_name(self):
        moved = src("class TestB(Base):\n    def test_x(self):\n        self.assertTrue(zz())\n"
                    "        self.assertTrue(yy())\n        self.assertTrue(ww())\n")
        r = run({"t/test_a.py": THREE_ASSERTS}, {"t/test_a.py": "", "t/test_b.py": moved})
        self.assertEqual(r.removed, [])

    def test_test_file_deleted_with_its_module_is_cleanup(self):
        base = {"t/test_widget.py": "class TestW(B):\n    def test_it(self):\n        self.assertTrue(go())\n"}
        r = run(base, {}, {"app/widget.py": "x = 1\n"}, {})
        self.assertEqual(r.removed, [])
        self.assertEqual(names(r.removed_cleanup), ["TestW.test_it"])

    def test_control_same_name_in_another_class_does_not_hide_a_removal(self):
        base = {"t/test_a.py": THREE_ASSERTS, "t/test_c.py": THREE_ASSERTS.replace("TestA", "TestC")}
        head = {"t/test_a.py": "", "t/test_c.py": THREE_ASSERTS.replace("TestA", "TestC")}
        r = run(base, head)
        self.assertEqual(names(r.removed), ["TestA.test_x"])


class TestAssertionsRemoved(unittest.TestCase):
    def test_two_assertions_removed_is_reported(self):
        head = src(
            """
            class TestA(Base):
                def test_x(self):
                    self.assertEqual(1, f())
            """
        )
        r = run({"t/test_a.py": THREE_ASSERTS}, {"t/test_a.py": head})
        self.assertEqual(names(r.assertions_removed), ["TestA.test_x"])
        self.assertEqual((r.assertions_removed[0].before, r.assertions_removed[0].after), (3, 1))

    def test_control_one_assertion_removed_is_not_reported(self):
        head = THREE_ASSERTS.replace('        self.assertIn("a", h())\n', "")
        r = run({"t/test_a.py": THREE_ASSERTS}, {"t/test_a.py": head})
        self.assertEqual(r.assertions_removed, [])

    def test_bare_assert_statements_count(self):
        base = src("class T(B):\n    def test_x(self):\n        assert a\n        assert b\n        assert c\n")
        head = src("class T(B):\n    def test_x(self):\n        assert a\n")
        r = run({"t/test_a.py": base}, {"t/test_a.py": head})
        self.assertEqual(names(r.assertions_removed), ["T.test_x"])

    def test_control_assert_words_in_comments_and_strings_do_not_count(self):
        base = src(
            """
            class T(B):
                def test_x(self):
                    # self.assertEqual(1, 2)
                    s = "self.assertEqual(1, 2); assert x"
                    self.assertTrue(f())
            """
        )
        head = src("class T(B):\n    def test_x(self):\n        self.assertTrue(f())\n")
        r = run({"t/test_a.py": base}, {"t/test_a.py": head})
        self.assertEqual(r.assertions_removed, [])

    def test_control_refactor_into_new_assert_helper_is_not_reported(self):
        head = src(
            """
            class TestA(Base):
                def test_x(self):
                    self.assertDocExists("Member", f())
            """
        )
        r = run({"t/test_a.py": THREE_ASSERTS}, {"t/test_a.py": head})
        self.assertEqual(r.assertions_removed, [])

    def test_removal_replaced_by_non_assert_call_is_reported(self):
        head = src(
            """
            class TestA(Base):
                def test_x(self):
                    self.setup_thing()
                    self.assertEqual(1, f())
            """
        )
        r = run({"t/test_a.py": THREE_ASSERTS}, {"t/test_a.py": head})
        self.assertEqual(names(r.assertions_removed), ["TestA.test_x"])

    def test_control_asserts_added_are_not_reported(self):
        head = THREE_ASSERTS + "            self.assertTrue(z())\n"
        r = run({"t/test_a.py": THREE_ASSERTS}, {"t/test_a.py": head})
        self.assertEqual(r.assertions_removed, [])


class TestAssertionsCleanup(unittest.TestCase):
    BASE = src(
        """
        class T(B):
            def test_x(self):
                self.assertTrue(legacy_widget_builder())
                self.assertEqual(legacy_widget_builder(), 1)
                self.assertTrue(keep_this())
        """
    )
    HEAD = src("class T(B):\n    def test_x(self):\n        self.assertTrue(keep_this())\n")

    def test_assertions_on_deleted_code_are_cleanup(self):
        prod = {"app/w.py": "def legacy_widget_builder():\n    return 1\n"}
        r = run({"t/test_a.py": self.BASE}, {"t/test_a.py": self.HEAD}, prod, {"app/w.py": ""})
        self.assertEqual(r.assertions_removed, [])
        self.assertEqual(names(r.assertions_cleanup), ["T.test_x"])

    def test_control_assertions_on_surviving_code_are_still_reported(self):
        prod = {"app/w.py": "def legacy_widget_builder():\n    return 1\n"}
        r = run({"t/test_a.py": self.BASE}, {"t/test_a.py": self.HEAD}, prod, prod)
        self.assertEqual(names(r.assertions_removed), ["T.test_x"])
        self.assertEqual(r.assertions_cleanup, [])


class TestConstantAsserts(unittest.TestCase):
    CASES = [
        "self.assertTrue(True)",
        "assert True",
        "self.assertEqual(1, 1)",
        'self.assertIsNotNone("x")',
        "self.assertFalse(False)",
        "assert 1",
        "self.assertEqual(a, a)",
    ]

    def test_each_constant_shape_is_reported_when_new(self):
        for stmt in self.CASES:
            with self.subTest(stmt=stmt):
                head = src(f"class T(B):\n    def test_x(self):\n        self.assertTrue(f())\n        {stmt}\n")
                base = src("class T(B):\n    def test_x(self):\n        self.assertTrue(f())\n")
                r = run({"t/test_a.py": base}, {"t/test_a.py": head})
                self.assertEqual(len(r.constant_asserts), 1)

    def test_control_real_asserts_are_not_constant(self):
        # assertTrue(False) can never pass, so it is not a weakening either.
        for stmt in ["self.assertTrue(x)", "self.assertEqual(f(), 1)", "self.assertEqual(f(), f())",
                     "self.assertIsNotNone(m)", "assert x == 1", "self.assertTrue(False, 'msg')"]:
            with self.subTest(stmt=stmt):
                head = src(f"class T(B):\n    def test_x(self):\n        {stmt}\n")
                r = run({}, {"t/test_a.py": head})
                self.assertEqual(r.constant_asserts, [])

    def test_control_existing_constant_assert_untouched_is_not_reported(self):
        both = src("class T(B):\n    def test_x(self):\n        self.assertTrue(True)\n        assert True\n")
        r = run({"t/test_a.py": both}, {"t/test_a.py": both + "    def test_y(self):\n        self.assertTrue(f())\n"})
        self.assertEqual(r.constant_asserts, [])

    def test_control_constant_assert_moved_with_its_test_is_not_reported(self):
        both = src("class T(B):\n    def test_x(self):\n        self.assertTrue(True)\n")
        r = run({"t/test_a.py": both}, {"t/test_a.py": "", "t/test_b.py": both})
        self.assertEqual(r.constant_asserts, [])

    def test_a_second_identical_constant_assert_is_new(self):
        one = src("class T(B):\n    def test_x(self):\n        self.assertTrue(True)\n")
        two = one + "        self.assertTrue(True)\n"
        r = run({"t/test_a.py": one}, {"t/test_a.py": two})
        self.assertEqual(len(r.constant_asserts), 1)

    def test_constant_in_comment_or_string_is_ignored(self):
        head = src('class T(B):\n    def test_x(self):\n        s = "assert True"  # assertTrue(True)\n        self.assertTrue(f())\n')
        r = run({}, {"t/test_a.py": head})
        self.assertEqual(r.constant_asserts, [])


class TestNewSkips(unittest.TestCase):
    BASE = src("class T(B):\n    def test_x(self):\n        self.assertTrue(f())\n")

    def head_with(self, body, decorator=""):
        return src(f"class T(B):\n{decorator}    def test_x(self):\n{body}")

    def test_each_skip_shape_is_reported(self):
        shapes = {
            "skipTest": (self.head_with("        self.skipTest('no')\n        self.assertTrue(f())\n"), ""),
            "decorator": (self.head_with("        self.assertTrue(f())\n", "    @unittest.skip('no')\n"), ""),
            "skipIf": (self.head_with("        self.assertTrue(f())\n", "    @unittest.skipIf(c, 'no')\n"), ""),
            "early return": (self.head_with("        if not c:\n            return\n        self.assertTrue(f())\n"), ""),
            "raise SkipTest": (self.head_with("        raise unittest.SkipTest('x')\n"), ""),
            "pytest.skip": (self.head_with("        pytest.skip('x')\n        self.assertTrue(f())\n"), ""),
        }
        for label, (head, _) in shapes.items():
            with self.subTest(label=label):
                r = run({"t/test_a.py": self.BASE}, {"t/test_a.py": head})
                self.assertEqual(names(r.new_skips), ["T.test_x"])

    def test_class_level_skip_decorator_is_reported(self):
        head = "@unittest.skip('x')\n" + self.BASE
        r = run({"t/test_a.py": self.BASE}, {"t/test_a.py": head})
        self.assertEqual(names(r.new_skips), ["T"])

    def test_skip_in_new_test_is_reported(self):
        head = self.BASE + "    def test_new(self):\n        self.skipTest('x')\n"
        r = run({"t/test_a.py": self.BASE}, {"t/test_a.py": head})
        self.assertEqual(names(r.new_skips), ["T.test_new"])

    def test_control_return_after_the_assertions_is_not_a_skip(self):
        head = self.head_with("        self.assertTrue(f())\n        return\n")
        r = run({"t/test_a.py": self.BASE}, {"t/test_a.py": head})
        self.assertEqual(r.new_skips, [])

    def test_control_return_inside_nested_helper_is_not_a_skip(self):
        head = self.head_with("        def inner():\n            return 1\n        self.assertTrue(inner())\n")
        r = run({"t/test_a.py": self.BASE}, {"t/test_a.py": head})
        self.assertEqual(r.new_skips, [])

    def test_control_preexisting_skip_is_not_new(self):
        both = self.head_with("        self.skipTest('no')\n        self.assertTrue(f())\n")
        r = run({"t/test_a.py": both}, {"t/test_a.py": both + "    def test_y(self):\n        self.assertTrue(1 + f())\n"})
        self.assertEqual(r.new_skips, [])

    def test_control_skipped_test_moved_to_another_file_is_not_new(self):
        both = self.head_with("        self.skipTest('no')\n        self.assertTrue(f())\n")
        r = run({"t/test_a.py": both}, {"t/test_a.py": "", "t/test_b.py": both})
        self.assertEqual(r.new_skips, [])

    def test_skip_in_setup_is_reported(self):
        head = self.BASE + "    def setUp(self):\n        self.skipTest('x')\n"
        r = run({"t/test_a.py": self.BASE}, {"t/test_a.py": head})
        self.assertEqual(names(r.new_skips), ["T.setUp"])


class TestGitAndCli(unittest.TestCase):
    def git(self, cwd, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                       capture_output=True)

    def test_end_to_end_against_a_real_repo_and_exit_code_is_zero(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.git(root, "init", "-q", "-b", "develop")
            (root / "tests").mkdir()
            (root / "tests" / "test_a.py").write_text(THREE_ASSERTS)
            self.git(root, "add", "-A")
            self.git(root, "commit", "-qm", "base")
            self.git(root, "checkout", "-qb", "feature")
            (root / "tests" / "test_a.py").write_text(
                "class TestA(Base):\n    def test_x(self):\n        self.skipTest('x')\n        assert True\n"
            )
            self.git(root, "commit", "-qam", "weaken")
            proc = subprocess.run(
                [sys.executable, str(_MOD_PATH), "--base", "develop", "--repo", str(root)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = proc.stdout
            self.assertIn("assertions removed", out)
            self.assertIn("TestA.test_x", out)
            self.assertIn("new skips", out)
            self.assertIn("constant asserts", out)

    def test_unknown_base_ref_still_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            self.git(d, "init", "-q", "-b", "develop")
            proc = subprocess.run(
                [sys.executable, str(_MOD_PATH), "--base", "origin/nope", "--repo", d],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("skipped", proc.stdout.lower())


if __name__ == "__main__":
    unittest.main()
