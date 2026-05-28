"""
Regression tests for except_order_validator.

Pins the v1 rule: in a single try block, ``except frappe.ValidationError``
must NOT appear before ``except frappe.PermissionError`` — post-PR #107
our local ``verenigingen.utils.error_handling.PermissionError``
multi-inherits from both, so the ValidationError handler shadows the
PermissionError one.

The validator is intentionally narrow in v1; built-in Python subclass
cases (``except OSError`` before ``except FileNotFoundError``) are out
of scope and not asserted here.
"""

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# The validator lives at apps/verenigingen/scripts/validation/. Make it
# importable from this test file (apps/verenigingen/verenigingen/tests/).
# ``Path(__file__).resolve().parents[2]`` is the verenigingen app root.
APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT / "scripts" / "validation"))

import except_order_validator as v  # noqa: E402


class TestExceptOrderValidator(unittest.TestCase):
    """Pins behavior of scripts/validation/except_order_validator.py.

    Lives in ``verenigingen/tests/`` (not ``scripts/validation/tests/``)
    so ``bench --site veg11.veganisme.org run-tests --app verenigingen``
    + pytest discovery (testpaths = verenigingen/tests) pick it up
    automatically.
    """

    def _write(self, source: str) -> Path:
        """Write a Python snippet to a tempfile and return its path.

        Cleanup is registered immediately so the file is removed even if
        the test errors out — without ``addCleanup`` the tempfiles leak
        in ``/tmp`` each run (caught by senior code reviewer on PR #110).
        """
        fd = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        )
        fd.write(textwrap.dedent(source))
        fd.close()
        path = Path(fd.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_qualified_perm_before_validation_is_ok(self):
        path = self._write(
            """
            import frappe
            def f():
                try: pass
                except frappe.PermissionError: pass
                except frappe.ValidationError: pass
            """
        )
        self.assertEqual(v.check_file(path), [])

    def test_qualified_validation_before_perm_is_violation(self):
        path = self._write(
            """
            import frappe
            def f():
                try: pass
                except frappe.ValidationError: pass
                except frappe.PermissionError: pass
            """
        )
        violations = v.check_file(path)
        self.assertEqual(len(violations), 1)
        self.assertIn("frappe.PermissionError", violations[0].message)
        self.assertIn("frappe.ValidationError", violations[0].message)

    def test_bare_via_from_frappe_import_is_resolved(self):
        """`from frappe import PermissionError, ValidationError` then bare names."""
        path = self._write(
            """
            from frappe import PermissionError, ValidationError
            def f():
                try: pass
                except ValidationError: pass
                except PermissionError: pass
            """
        )
        violations = v.check_file(path)
        self.assertEqual(len(violations), 1)

    def test_bare_without_frappe_import_is_not_flagged(self):
        """Bare names without `from frappe import` could be the Python
        built-in PermissionError, not ours. Don't flag — false positive."""
        path = self._write(
            """
            def f():
                try: pass
                except ValidationError: pass
                except PermissionError: pass
            """
        )
        self.assertEqual(v.check_file(path), [])

    def test_tuple_in_single_handler_is_ok(self):
        """Catching both in the same tuple has no ordering issue."""
        path = self._write(
            """
            import frappe
            def f():
                try: pass
                except (frappe.PermissionError, frappe.ValidationError): pass
            """
        )
        self.assertEqual(v.check_file(path), [])

    def test_only_validation_handler_is_ok(self):
        """Only one of the pair — no order issue."""
        path = self._write(
            """
            import frappe
            def f():
                try: pass
                except frappe.ValidationError: pass
                except Exception: pass
            """
        )
        self.assertEqual(v.check_file(path), [])

    def test_only_permission_handler_is_ok(self):
        """Only one of the pair — no order issue."""
        path = self._write(
            """
            import frappe
            def f():
                try: pass
                except frappe.PermissionError: pass
                except Exception: pass
            """
        )
        self.assertEqual(v.check_file(path), [])

    def test_unrelated_pair_is_not_flagged(self):
        """ValueError + KeyError — different concern, not v1 scope."""
        path = self._write(
            """
            def f():
                try: pass
                except ValueError: pass
                except KeyError: pass
            """
        )
        self.assertEqual(v.check_file(path), [])

    def test_intervening_handler_does_not_excuse_the_bug(self):
        """ValidationError → KeyError → PermissionError still flags
        because the PermissionError handler is still shadowed."""
        path = self._write(
            """
            import frappe
            def f():
                try: pass
                except frappe.ValidationError: pass
                except KeyError: pass
                except frappe.PermissionError: pass
            """
        )
        violations = v.check_file(path)
        self.assertEqual(len(violations), 1)

    def test_nested_try_blocks_evaluated_independently(self):
        """Outer try wrong-ordered; inner try correctly ordered. Only
        the outer violation should be reported."""
        path = self._write(
            """
            import frappe
            def f():
                try:
                    try: pass
                    except frappe.PermissionError: pass
                    except frappe.ValidationError: pass
                except frappe.ValidationError: pass
                except frappe.PermissionError: pass
            """
        )
        violations = v.check_file(path)
        self.assertEqual(len(violations), 1)

    def test_aliased_import_is_v1_gap(self):
        """`from frappe import ValidationError as VE` — the local name
        is VE, not ValidationError. v1 deliberately doesn't resolve
        aliases (rare in this codebase); pin the gap so the design
        intent is explicit.
        """
        path = self._write(
            """
            from frappe import ValidationError as VE, PermissionError as PE
            def f():
                try: pass
                except VE: pass
                except PE: pass
            """
        )
        # Aliased local names slip through — documented false negative.
        self.assertEqual(v.check_file(path), [])

    def test_syntax_error_file_is_skipped_silently(self):
        """Validator must not crash on unparseable files."""
        path = self._write("def broken(:\n    pass\n")
        self.assertEqual(v.check_file(path), [])

    def test_bare_except_is_ignored(self):
        """``except:`` (no type) cannot be the start of a routing bug."""
        path = self._write(
            """
            import frappe
            def f():
                try: pass
                except frappe.ValidationError: pass
                except: pass
            """
        )
        self.assertEqual(v.check_file(path), [])

    def test_try_except_star_pep654_is_inspected(self):
        """PEP 654 ``try/except*`` (exception groups, Python 3.11+) is a
        separate AST node (``ast.TryStar``). The validator handles both
        so introducing an exception-group block can't sneak past the lint
        (covers skeptical reviewer's MINOR-5 on PR #110).
        """
        path = self._write(
            """
            import frappe
            def f():
                try: pass
                except* frappe.ValidationError: pass
                except* frappe.PermissionError: pass
            """
        )
        violations = v.check_file(path)
        self.assertEqual(len(violations), 1)


if __name__ == "__main__":
    unittest.main()
