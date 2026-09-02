#!/usr/bin/env python3
"""Unit tests for scripts/validation/dynamic_link_append_validator.py.

Pure-Python (no bench/site needed). Every positive case pairs with a negative
control, per this repo's testing convention -- a detector that flags everything
and one that flags nothing both pass a one-sided test.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "dynamic_link_append_validator.py"
_spec = importlib.util.spec_from_file_location("dynamic_link_append_validator", _MOD_PATH)
validator = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = validator
_spec.loader.exec_module(validator)


def _write_doctype_json(root: Path, name: str, fields: list[dict]):
    d = root / name.lower().replace(" ", "_")
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name.lower().replace(' ', '_')}.json").write_text(
        json.dumps({"doctype": "DocType", "name": name, "fields": fields})
    )


CHILD_DOCTYPE_FIELDS = [
    {"fieldname": "widget", "fieldtype": "Dynamic Link", "options": "widget_doctype"},
    {"fieldname": "widget_doctype", "fieldtype": "Data"},
]

PARENT_DOCTYPE_FIELDS = [
    {"fieldname": "widgets", "fieldtype": "Table", "options": "Widget Link"},
]

OFFENDING_SOURCE = (
    "def link(parent, widget_name):\n"
    "    parent.append('widgets', {'widget': widget_name, 'is_current': 1})\n"
)

INNOCENT_SOURCE = (
    "def link(parent, widget_name):\n"
    "    parent.append(\n"
    "        'widgets',\n"
    "        {'widget': widget_name, 'widget_doctype': 'Widget', 'is_current': 1},\n"
    "    )\n"
)

SPREAD_SOURCE = (
    "def link(parent, widget_name, extra):\n"
    "    parent.append('widgets', {'widget': widget_name, **extra})\n"
)

COMPANION_LITERAL_NONE_SOURCE = (
    "def link(parent, widget_name):\n"
    "    parent.append(\n"
    "        'widgets',\n"
    "        {'widget': widget_name, 'widget_doctype': None, 'is_current': 1},\n"
    "    )\n"
)

DYNLINK_LITERAL_NONE_SOURCE = (
    "def link(parent):\n"
    "    parent.append('widgets', {'widget': None, 'is_current': 1})\n"
)

DYNLINK_ABSENT_SOURCE = (
    "def link(parent):\n"
    "    parent.append('widgets', {'is_current': 1})\n"
)

NON_DICT_SOURCE = (
    "def link(parent, entry):\n"
    "    parent.append('widgets', entry)\n"
)

UNRELATED_APPEND_SOURCE = (
    "def collect(results):\n"
    "    results.append('some string')\n"
)


class TestBuildSchemaMaps(unittest.TestCase):
    def test_maps_table_field_and_dynamic_link(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_doctype_json(root, "Widget Link", CHILD_DOCTYPE_FIELDS)
            _write_doctype_json(root, "Widget Parent", PARENT_DOCTYPE_FIELDS)
            table_fields, dynlink_fields = validator.build_schema_maps(root)
            self.assertEqual(table_fields.get("widgets"), {"Widget Link"})
            self.assertEqual(dynlink_fields.get("Widget Link"), [("widget", "widget_doctype")])

    def test_ambiguous_table_field_maps_to_multiple_doctypes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_doctype_json(root, "Widget Link", CHILD_DOCTYPE_FIELDS)
            _write_doctype_json(root, "Widget Parent", PARENT_DOCTYPE_FIELDS)
            _write_doctype_json(
                root,
                "Other Parent",
                [{"fieldname": "widgets", "fieldtype": "Table", "options": "Other Widget Link"}],
            )
            table_fields, _ = validator.build_schema_maps(root)
            self.assertEqual(table_fields.get("widgets"), {"Widget Link", "Other Widget Link"})


class TestFindOffendingAppends(unittest.TestCase):
    def setUp(self):
        self.table_fields = {"widgets": {"Widget Link"}}
        self.dynlink_fields = {"Widget Link": [("widget", "widget_doctype")]}

    def _findings(self, source: str):
        with tempfile.TemporaryDirectory() as d:
            py_path = Path(d) / "site.py"
            py_path.write_text(source)
            return validator.find_offending_appends(py_path, self.table_fields, self.dynlink_fields)

    def test_flags_dynamic_link_value_without_companion(self):
        findings = self._findings(OFFENDING_SOURCE)
        self.assertEqual(len(findings), 1)
        lineno, child_doctype, dynlink_field, companion_field = findings[0]
        self.assertEqual(child_doctype, "Widget Link")
        self.assertEqual(dynlink_field, "widget")
        self.assertEqual(companion_field, "widget_doctype")

    def test_does_not_flag_when_companion_is_set(self):
        self.assertEqual(self._findings(INNOCENT_SOURCE), [])

    def test_does_not_flag_a_spread_dict(self):
        # Cannot verify statically whether the companion is inside `extra` --
        # a false negative here is the deliberate tradeoff, not a bug.
        self.assertEqual(self._findings(SPREAD_SOURCE), [])

    def test_does_not_flag_a_non_dict_argument(self):
        self.assertEqual(self._findings(NON_DICT_SOURCE), [])

    def test_does_not_flag_unrelated_append_calls(self):
        self.assertEqual(self._findings(UNRELATED_APPEND_SOURCE), [])

    def test_does_not_flag_ambiguous_table_fieldname(self):
        table_fields = {"widgets": {"Widget Link", "Other Widget Link"}}
        with tempfile.TemporaryDirectory() as d:
            py_path = Path(d) / "site.py"
            py_path.write_text(OFFENDING_SOURCE)
            findings = validator.find_offending_appends(py_path, table_fields, self.dynlink_fields)
        self.assertEqual(findings, [])

    def test_flags_companion_set_to_literal_none(self):
        # A companion explicitly set to None persists as SQL NULL exactly like
        # an absent key -- both must be caught.
        findings = self._findings(COMPANION_LITERAL_NONE_SOURCE)
        self.assertEqual(len(findings), 1)

    def test_does_not_flag_dynamic_link_set_to_literal_none(self):
        # _validate_links() skips a falsy Dynamic Link value entirely, so a
        # missing companion is irrelevant when the link itself is None.
        self.assertEqual(self._findings(DYNLINK_LITERAL_NONE_SOURCE), [])

    def test_does_not_flag_dynamic_link_field_absent(self):
        self.assertEqual(self._findings(DYNLINK_ABSENT_SOURCE), [])


class TestIsTestPath(unittest.TestCase):
    def test_flags_tests_directory(self):
        self.assertTrue(validator._is_test_path(Path("verenigingen/tests/sepa/test_foo.py")))

    def test_flags_test_prefixed_filename(self):
        self.assertTrue(
            validator._is_test_path(Path("verenigingen/doctype/member/test_member.py"))
        )

    def test_does_not_flag_production_file(self):
        self.assertFalse(
            validator._is_test_path(Path("verenigingen/services/payment/sepa_mandate_manager.py"))
        )


if __name__ == "__main__":
    unittest.main()
