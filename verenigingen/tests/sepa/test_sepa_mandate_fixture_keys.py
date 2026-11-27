"""Structural gate: test fixtures must not build a SEPA Mandate with ``mandate_date`` (#1269).

``SEPA Mandate`` has no ``mandate_date`` field; the real, required one is ``sign_date``.
``frappe.get_doc({...})`` silently keeps an unknown key as a stray attribute, so a
fixture that carries ONLY ``mandate_date`` constructs a mandate whose ``sign_date`` is
None and fails the mandatory check on insert, while one that carries both has a dead
redundant key. Measured on test_site_7: ``get_doc({"doctype": "SEPA Mandate",
"mandate_date": ...}).sign_date`` is None.

None of the field validators caught this: they check attribute access / get_value /
SQL on production code, and none inspects the keys of a ``frappe.get_doc({...})``
dict literal. This gate does that for the one doctype and the one stale name.
"""

import ast
import json
import os
import unittest

TESTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANDATE_JSON = os.path.join(
    os.path.dirname(TESTS_ROOT),
    "verenigingen_payments",
    "doctype",
    "sepa_mandate",
    "sepa_mandate.json",
)
STALE_KEY = "mandate_date"
REAL_KEY = "sign_date"


def _mandate_dict_keysets(source):
    """Yield (lineno, set of constant string keys) for every SEPA Mandate dict literal."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        pairs = {
            k.value: v
            for k, v in zip(node.keys, node.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        doctype = pairs.get("doctype")
        if isinstance(doctype, ast.Constant) and doctype.value == "SEPA Mandate":
            # A `**spread` key (None in ast) can supply sign_date; such a dict is not
            # judged for a MISSING key, only for a stale one.
            yield node.lineno, set(pairs) | ({"**"} if None in node.keys else set())


def _scan_tests_tree():
    found = []
    for root, _dirs, files in os.walk(TESTS_ROOT):
        for name in files:
            if not name.endswith(".py") or name == os.path.basename(__file__):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            if "SEPA Mandate" not in source:
                continue
            for lineno, keys in _mandate_dict_keysets(source):
                found.append((os.path.relpath(path, TESTS_ROOT), lineno, keys))
    return found


class TestSepaMandateFixtureKeys(unittest.TestCase):
    def test_schema_premise(self):
        """The gate's premise: sign_date is a real field, mandate_date is not."""
        with open(MANDATE_JSON, encoding="utf-8") as fh:
            fieldnames = {f["fieldname"] for f in json.load(fh)["fields"]}
        self.assertIn(REAL_KEY, fieldnames)
        self.assertNotIn(STALE_KEY, fieldnames)

    def test_control_scanner_flags_a_stale_dict(self):
        """Control: the scanner sees a stale dict, a good dict, and ignores other doctypes."""
        source = (
            'a = {"doctype": "SEPA Mandate", "mandate_date": 1}\n'
            'b = {"doctype": "SEPA Mandate", "sign_date": 1}\n'
            'c = {"doctype": "Member", "mandate_date": 1}\n'
        )
        keysets = [keys for _lineno, keys in _mandate_dict_keysets(source)]
        self.assertEqual(len(keysets), 2)
        self.assertEqual(sum(STALE_KEY in k for k in keysets), 1)

    def test_scan_finds_mandate_fixtures(self):
        """Control: the real scan sees SEPA Mandate dict literals at all."""
        self.assertGreater(len(_scan_tests_tree()), 10)

    def test_no_fixture_uses_the_stale_mandate_date_key(self):
        stale = [
            f"{path}:{lineno}" for path, lineno, keys in _scan_tests_tree() if STALE_KEY in keys
        ]
        self.assertEqual(stale, [], f"SEPA Mandate has no `{STALE_KEY}` field; use `{REAL_KEY}`")

    def test_every_fixture_carries_the_required_sign_date(self):
        missing = [
            f"{path}:{lineno}"
            for path, lineno, keys in _scan_tests_tree()
            if REAL_KEY not in keys and "**" not in keys
        ]
        self.assertEqual(missing, [], f"SEPA Mandate fixtures missing required `{REAL_KEY}`")
