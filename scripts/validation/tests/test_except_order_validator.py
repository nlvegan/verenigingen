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

# Import the validator module directly without installing — the script
# directory is sibling to ``tests/``.
SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import except_order_validator as v  # noqa: E402


def _write(source: str) -> Path:
    """Write a Python snippet to a tempfile and return its path."""
    fd = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    )
    fd.write(textwrap.dedent(source))
    fd.close()
    return Path(fd.name)


class TestExceptOrderValidator(unittest.TestCase):
    def test_qualified_perm_before_validation_is_ok(self):
        path = _write(
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
        path = _write(
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
        path = _write(
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
        path = _write(
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
        path = _write(
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
        path = _write(
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
        path = _write(
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
        path = _write(
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
        path = _write(
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
        path = _write(
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

    def test_aliased_import_is_resolved(self):
        """`from frappe import ValidationError as VE` — the local name
        is VE, not ValidationError. Bare VE/PE should still resolve."""
        path = _write(
            """
            from frappe import ValidationError as VE, PermissionError as PE
            def f():
                try: pass
                except VE: pass
                except PE: pass
            """
        )
        # Local names are VE / PE — but our rule looks for the LOGICAL
        # name "ValidationError"/"PermissionError" not the alias. Aliased
        # imports are a deliberate v1 gap (false negative) — they're rare
        # in this codebase. Document the gap rather than over-engineer.
        self.assertEqual(v.check_file(path), [])

    def test_syntax_error_file_is_skipped_silently(self):
        """Validator must not crash on unparseable files."""
        path = _write("def broken(:\n    pass\n")
        self.assertEqual(v.check_file(path), [])

    def test_bare_except_is_ignored(self):
        """``except:`` (no type) cannot be the start of a routing bug."""
        path = _write(
            """
            import frappe
            def f():
                try: pass
                except frappe.ValidationError: pass
                except: pass
            """
        )
        self.assertEqual(v.check_file(path), [])


if __name__ == "__main__":
    unittest.main()
