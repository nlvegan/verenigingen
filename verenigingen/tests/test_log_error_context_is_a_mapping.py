"""Guard: `utils.error_handling.log_error`'s second argument is a context dict.

`log_error(error, context=None, module=None)` starts with
``(context or {}).get("trace_id")``. A **string** there is truthy, so `.get` is
called on a `str` and the function raises ``AttributeError`` -- *from inside the
except handler that called it*.

Three call sites did exactly that, and two were mid-loop:

* ``api/payment_processing.py`` -- the per-member ``except`` in
  ``send_overdue_payment_reminders``. The ``continue`` after it was unreachable,
  so the first member whose send failed aborted the whole reminder run.
* ``api/payment_processing.py`` -- the same shape in the bulk-action loop
  (write-offs, late fees, collection-agency marking), which stopped partway.
* ``api/membership_application.py`` -- replaced a clean ``OperationResult.fail``
  with an unhandled error on the email-validation path.

The confusing part is that Frappe's *own* ``frappe.log_error`` really does take
``(title, message)`` strings, and this app calls that one backwards at ~1100
sites (see CLAUDE.md). So a string second argument looks idiomatic here and is
not: the bare name in these modules is the app's helper, whose second parameter
is a mapping.
"""

import ast
import pathlib
import unittest

import frappe

from verenigingen.utils.error_handling import log_error

APP_ROOT = pathlib.Path(__file__).resolve().parents[1]

BAD_SHAPE = """
from verenigingen.utils.error_handling import log_error

def handler(e):
    try:
        pass
    except Exception as e:
        log_error(f"it broke: {e}", "Some Title")
"""


def _string_context_calls(tree, path):
    """Bare `log_error(...)` calls passing a string where a mapping belongs."""
    imports_app_helper = any(
        isinstance(node, ast.ImportFrom)
        and node.module
        and "utils.error_handling" in node.module
        and any(alias.name == "log_error" for alias in node.names)
        for node in ast.walk(tree)
    )
    if not imports_app_helper:
        return []

    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "log_error":
            continue
        second = node.args[1] if len(node.args) >= 2 else None
        for kw in node.keywords:
            if kw.arg == "context":
                second = kw.value
        if isinstance(second, ast.Constant) and isinstance(second.value, str):
            found.append(f"{path}:{node.lineno}")
    return found


class TestLogErrorContextIsAMapping(unittest.TestCase):
    def test_no_call_site_passes_a_string_as_context(self):
        offenders = []
        this_file = pathlib.Path(__file__).resolve()
        for path in APP_ROOT.rglob("*.py"):
            if ".claude" in str(path):
                continue
            # This module deliberately calls the bad shape, inside assertRaises,
            # to pin why the scan matters.
            if path.resolve() == this_file:
                continue
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):
                continue
            offenders.extend(_string_context_calls(tree, path.relative_to(APP_ROOT)))

        self.assertEqual(
            offenders,
            [],
            "log_error's second argument is `context: dict`; a string makes the call raise "
            "AttributeError inside the handler that called it:\n  " + "\n  ".join(offenders),
        )

    def test_the_scan_can_fail(self):
        """Control: without this, a scanner that matched nothing would pass silently."""
        found = _string_context_calls(ast.parse(BAD_SHAPE), pathlib.Path("<synthetic>"))
        self.assertEqual(len(found), 1, "the scan no longer recognises the shape it exists to find")

    def test_a_string_context_really_does_raise(self):
        """Why the scan matters -- the failure is an exception, not a bad log line.

        Deliberately `Exception`, not `AttributeError`. Today the failure is an
        `AttributeError` from `(context or {}).get(...)`, but that type is an
        artefact of where the bug happens to land, not a contract. If `log_error`
        is later hardened to reject a non-mapping context up front (a `TypeError`
        would be the natural choice), that is the fix -- and pinning the current
        exception class here would make it read as a regression.
        """
        with self.assertRaises(Exception):
            log_error(ValueError("boom"), "Some Title")

        # Control: the documented shape is fine, so the assertion above is about
        # the string, not about log_error being broken for everyone.
        trace_id = log_error(ValueError("boom"), {"operation": "unit-test"})
        self.assertTrue(trace_id)


if __name__ == "__main__":
    unittest.main()
