"""#2948: one public delivery predicate for notify_administrators' return dict."""

import ast
import os
import unittest

import verenigingen
from verenigingen.utils.notification_helpers import was_delivered

APP_ROOT = os.path.dirname(verenigingen.__file__)
PRIVATE_COPY_NAMES = {"_was_delivered", "_delivered"}


class TestWasDelivered(unittest.TestCase):
    def test_delivered_only_when_success_not_skipped_and_something_written(self):
        self.assertTrue(was_delivered({"success": True, "notifications_created": 2}))

    def test_every_non_delivery_outcome_is_false(self):
        outcomes = {
            "none": None,
            "empty": {},
            "no recipient": {"success": False, "notifications_created": 0, "reason_code": "no_recipients"},
            "skipped key": {"success": True, "skipped": True, "notifications_created": 0},
            "skipped but counted": {"success": True, "skipped": True, "notifications_created": 3},
            "nothing written": {"success": True, "notifications_created": 0},
            "failed but counted": {"success": False, "notifications_created": 1},
        }
        for label, result in outcomes.items():
            with self.subTest(label):
                self.assertIs(was_delivered(result), False)

    def test_the_scan_sees_every_shape_of_a_private_copy(self):
        shapes = {
            "def": "def _was_delivered(r):\n    return True\n",
            "async def": "async def _delivered(r):\n    return True\n",
            "lambda assign": "_was_delivered = lambda r: True\n",
            "annotated assign": "_delivered: object = lambda r: True\n",
        }
        for label, source in shapes.items():
            with self.subTest(label):
                self.assertEqual(len(_private_copies(ast.parse(source))), 1)
        self.assertEqual(_private_copies(ast.parse("def was_delivered(r):\n    return True\n")), [])

    def test_no_module_keeps_a_private_copy_of_the_predicate(self):
        offenders = []
        for base, _dirs, files in os.walk(APP_ROOT):
            if os.sep + "tests" in base:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
                offenders.extend(f"{path}:{line}" for line in _private_copies(tree))
        self.assertEqual(offenders, [])


def _private_copies(tree):
    """Line numbers of any def, async def or assignment (lambda) binding a banned name."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in PRIVATE_COPY_NAMES:
            lines.append(node.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id in PRIVATE_COPY_NAMES for t in targets):
                lines.append(node.lineno)
    return lines
