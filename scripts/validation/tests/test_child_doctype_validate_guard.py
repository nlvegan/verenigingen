#!/usr/bin/env python3
"""Unit tests for scripts/validation/child_doctype_validate_guard.py.

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

_MOD_PATH = Path(__file__).resolve().parents[1] / "child_doctype_validate_guard.py"
_spec = importlib.util.spec_from_file_location("child_doctype_validate_guard", _MOD_PATH)
guard = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = guard
_spec.loader.exec_module(guard)


def _make_doctype_dir(root: Path, name: str, *, istable: bool, py_source: str):
    """Write a <root>/<name>/<name>.json + .py pair, doctype-folder-shaped."""
    d = root / name
    d.mkdir(parents=True)
    json_path = d / f"{name}.json"
    json_path.write_text(
        json.dumps({"doctype": "DocType", "name": name, "istable": 1 if istable else 0})
    )
    py_path = d / f"{name}.py"
    py_path.write_text(py_source)
    return json_path, py_path


CHILD_WITH_VALIDATE = (
    "import frappe\n"
    "from frappe.model.document import Document\n\n\n"
    "class Thing(Document):\n"
    "    def validate(self):\n"
    "        if not self.foo:\n"
    "            frappe.throw('foo required')\n"
)

PARENT_WITH_VALIDATE = CHILD_WITH_VALIDATE  # identical source; only istable differs

CHILD_NO_VALIDATE = (
    "import frappe\n"
    "from frappe.model.document import Document\n\n\n"
    "class Thing(Document):\n"
    "    def before_insert(self):\n"
    "        pass\n"
)

CHILD_WITH_EXEMPTED_VALIDATE = (
    "import frappe\n"
    "from frappe.model.document import Document\n\n\n"
    "class Thing(Document):\n"
    "    def validate(self):  # child-validate-ok: invoked directly, never via parent.save()\n"
    "        pass\n"
)

CHILD_WITH_NESTED_VALIDATE_HELPER = (
    "import frappe\n"
    "from frappe.model.document import Document\n\n\n"
    "class Thing(Document):\n"
    "    def before_insert(self):\n"
    "        def validate(x):\n"  # local function named validate, not a controller hook
    "            return x\n"
    "        return validate(1)\n"
)


class TestIsChildDoctypeJson(unittest.TestCase):
    def test_flags_istable_1(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text(json.dumps({"doctype": "DocType", "istable": 1}))
            self.assertTrue(guard.is_child_doctype_json(p))

    def test_does_not_flag_istable_0(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text(json.dumps({"doctype": "DocType", "istable": 0}))
            self.assertFalse(guard.is_child_doctype_json(p))

    def test_does_not_flag_non_doctype_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text(json.dumps({"doctype": "Client Script", "istable": 1}))
            self.assertFalse(guard.is_child_doctype_json(p))

    def test_tolerates_a_list_shaped_json_file(self):
        """Some JSON files in this repo (fixtures/customizations) are top-level lists."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text(json.dumps([{"doctype": "DocType", "istable": 1}]))
            self.assertFalse(guard.is_child_doctype_json(p))

    def test_tolerates_malformed_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text("{not valid json")
            self.assertFalse(guard.is_child_doctype_json(p))


class TestFindValidateDefs(unittest.TestCase):
    def test_finds_a_controller_validate(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.py"
            p.write_text(CHILD_WITH_VALIDATE)
            hits = guard.find_validate_defs(p)
            self.assertEqual(len(hits), 1)
            lineno, exempt = hits[0]
            self.assertEqual(lineno, 6)
            self.assertFalse(exempt)

    def test_does_not_find_validate_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.py"
            p.write_text(CHILD_NO_VALIDATE)
            self.assertEqual(guard.find_validate_defs(p), [])

    def test_exempt_marker_is_honoured(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.py"
            p.write_text(CHILD_WITH_EXEMPTED_VALIDATE)
            hits = guard.find_validate_defs(p)
            self.assertEqual(len(hits), 1)
            _, exempt = hits[0]
            self.assertTrue(exempt)

    def test_ignores_a_nested_function_named_validate(self):
        """A local helper named `validate` inside another method is not the
        controller hook -- it never runs at parent-save time either way, so
        flagging it would just be noise unrelated to #596's mechanism."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.py"
            p.write_text(CHILD_WITH_NESTED_VALIDATE_HELPER)
            self.assertEqual(guard.find_validate_defs(p), [])


class TestCensusEndToEnd(unittest.TestCase):
    """The planted-violation proof: the gate must fail on a synthetic child
    controller with `def validate`, and must NOT fail on the same source sitting
    on a PARENT (istable: 0) DocType -- the control."""

    def test_planted_violation_is_caught(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            doctype_dir = root / "doctype"
            _make_doctype_dir(
                doctype_dir, "planted_child", istable=True, py_source=CHILD_WITH_VALIDATE
            )
            findings = guard.census([str(doctype_dir)])
            self.assertEqual(len(findings), 1, findings)
            rel, lineno = findings[0]
            self.assertIn("planted_child.py", rel)
            self.assertEqual(lineno, 6)

    def test_control_parent_doctype_is_not_flagged(self):
        """Same validate() body, but istable: 0 -- a normal parent DocType. This
        is the control: without it, a detector that flags every `def validate`
        anywhere would also pass the positive test above."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            doctype_dir = root / "doctype"
            _make_doctype_dir(
                doctype_dir, "planted_parent", istable=False, py_source=PARENT_WITH_VALIDATE
            )
            findings = guard.census([str(doctype_dir)])
            self.assertEqual(findings, [])

    def test_exempted_child_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            doctype_dir = root / "doctype"
            _make_doctype_dir(
                doctype_dir,
                "planted_exempt",
                istable=True,
                py_source=CHILD_WITH_EXEMPTED_VALIDATE,
            )
            findings = guard.census([str(doctype_dir)])
            self.assertEqual(findings, [])

    def test_symlinked_duplicate_is_reported_once(self):
        """A symlink alias for the same physical file must not double the finding
        (the trap a sibling validator was bitten by, #588)."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            doctype_dir = root / "doctype"
            _, py_path = _make_doctype_dir(
                doctype_dir, "planted_child", istable=True, py_source=CHILD_WITH_VALIDATE
            )
            alias = py_path.with_name("alias.py")
            try:
                alias.symlink_to(py_path)
            except OSError:
                self.skipTest("symlinks not supported in this environment")
            findings = guard.census([str(doctype_dir)])
            self.assertEqual(len(findings), 1, findings)

    def test_the_actual_15_are_all_clean_on_this_branch(self):
        """Confirms #596's fix actually emptied the census on the real tree, not
        just in a synthetic sandbox. Run from the repo, not a tempdir."""
        findings = guard.census(guard.SCAN_ROOTS)
        self.assertEqual(findings, [], f"child-validate guard should be at zero: {findings}")


class TestMain(unittest.TestCase):
    def test_main_exits_nonzero_on_a_planted_violation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            doctype_dir = root / "doctype"
            _make_doctype_dir(
                doctype_dir, "planted_child", istable=True, py_source=CHILD_WITH_VALIDATE
            )
            py_file = doctype_dir / "planted_child" / "planted_child.py"
            self.assertEqual(guard.main([str(py_file)]), 1)

    def test_main_exits_zero_on_a_clean_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            doctype_dir = root / "doctype"
            _make_doctype_dir(
                doctype_dir, "planted_child", istable=True, py_source=CHILD_NO_VALIDATE
            )
            py_file = doctype_dir / "planted_child" / "planted_child.py"
            self.assertEqual(guard.main([str(py_file)]), 0)

    def test_main_ignores_files_outside_a_doctype_directory(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "not_a_doctype_file.py"
            p.write_text(CHILD_WITH_VALIDATE)
            self.assertEqual(guard.main([str(p)]), 0)


if __name__ == "__main__":
    unittest.main()
