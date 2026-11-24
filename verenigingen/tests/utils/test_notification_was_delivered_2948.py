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
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name in PRIVATE_COPY_NAMES:
                        offenders.append(f"{path}:{node.lineno}")
        self.assertEqual(offenders, [])
