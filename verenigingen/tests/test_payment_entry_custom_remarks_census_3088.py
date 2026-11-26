"""
#3088 class guard: a function that builds a Payment Entry AND sets its remarks must also set
``custom_remarks``, or ERPNext's ``set_remarks`` regenerates the text on validate.

Shape scanned (non-test code, per function): the function body contains a Payment Entry
construction (a dict with ``"doctype": "Payment Entry"``, or ``new_doc("Payment Entry")``) and
a remarks write (a ``"remarks"`` dict key, or a ``.remarks =`` assignment), but contains no
``custom_remarks`` reference. Writers that delegate to a helper which sets it (the creation
service) never build the doc themselves, so they are not in scope. Not covered: a PE built in
one function and given remarks in another.
"""

import ast
import pathlib
import unittest

APP_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _is_test_path(path):
    parts = path.relative_to(APP_ROOT).parts
    return "tests" in parts or path.name.startswith("test_")


def _builds_payment_entry(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "doctype"
                    and isinstance(v, ast.Constant)
                    and v.value == "Payment Entry"
                ):
                    return True
        if (
            isinstance(n, ast.Call)
            and getattr(n.func, "attr", getattr(n.func, "id", "")) == "new_doc"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "Payment Entry"
        ):
            return True
    return False


def _writes_remarks(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Dict) and any(
            isinstance(k, ast.Constant) and k.value == "remarks" for k in n.keys
        ):
            return True
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Attribute) and t.attr == "remarks" for t in n.targets
        ):
            return True
    return False


def _mentions_custom_remarks(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and n.value == "custom_remarks":
            return True
        if isinstance(n, ast.Attribute) and n.attr == "custom_remarks":
            return True
    return False


def find_unprotected_remark_writers(source):
    tree = ast.parse(source)
    return [
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _builds_payment_entry(fn)
        and _writes_remarks(fn)
        and not _mentions_custom_remarks(fn)
    ]


class TestPaymentEntryRemarksCensus(unittest.TestCase):
    def test_scanner_flags_the_unprotected_shapes_and_passes_the_protected_ones(self):
        """Control: the scan must be able to find the bug, in both construction shapes."""
        dict_built = 'def f():\n    return frappe.get_doc({"doctype": "Payment Entry", "remarks": "x"})\n'
        attr_built = 'def g():\n    pe = frappe.new_doc("Payment Entry")\n    pe.remarks = "x"\n'
        protected = 'def h():\n    pe = frappe.new_doc("Payment Entry")\n    pe.remarks = "x"\n    pe.custom_remarks = 1\n'
        protected_dict = (
            'def i():\n    return frappe.get_doc({"doctype": "Payment Entry", "remarks": "x", "custom_remarks": 1})\n'
        )
        self.assertEqual(find_unprotected_remark_writers(dict_built), ["f"])
        self.assertEqual(find_unprotected_remark_writers(attr_built), ["g"])
        self.assertEqual(find_unprotected_remark_writers(protected), [])
        self.assertEqual(find_unprotected_remark_writers(protected_dict), [])

    def test_no_payment_entry_writer_loses_its_remarks_to_set_remarks(self):
        offenders = []
        scanned = 0
        for path in sorted(APP_ROOT.rglob("*.py")):
            if _is_test_path(path):
                continue
            source = path.read_text(encoding="utf-8")
            if "Payment Entry" not in source:
                continue
            scanned += 1
            offenders += [f"{path.relative_to(APP_ROOT)}::{name}" for name in find_unprotected_remark_writers(source)]
        self.assertGreater(scanned, 10, "fixture problem: the scan found almost no files")
        self.assertEqual(
            offenders,
            [],
            "these functions build a Payment Entry and set remarks without custom_remarks = 1; "
            "ERPNext's set_remarks will overwrite the text (#3088)",
        )
