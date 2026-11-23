#!/usr/bin/env python3
"""#2970: ast-field-analyzer must not read `ControllerClass.method` as a doctype field.

`can_clear_security_level(DirectDebitBatch.generate_sepa_xml)` names a METHOD on the
controller class. The analyzer mapped the identifier `DirectDebitBatch` to the doctype
"Direct Debit Batch" (variable-name mapping) and reported the attribute as a missing field.

Each test pairs the class-reference case with a control: a real missing field on a doc
INSTANCE in the same file must still be reported, so "report nothing" cannot pass.
Pure Python; reads this checkout's DocType JSONs. Run with:
    python -m unittest discover -s scripts/validation/tests -p 'test_ast_field_analyzer_class_reference.py'
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_VALIDATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VALIDATION))
sys.path.insert(0, str(_VALIDATION / "framework"))

import ast_field_analyzer as afa  # noqa: E402

_APP = Path(afa._get_app_path())
_ANALYZER = None


def _analyze(source: str):
    """Findings (field names) for `source`, written under the app root so the analyzer's
    app-relative path logic works. The file lives in a throwaway directory.

    Every fixture defines a `validate` function: that marks the file as a validation hook,
    which lifts a variable_name_mapping finding from LOW to MEDIUM (the hook's threshold),
    exactly as in direct_debit_batch.py. Without it the bug does not reproduce."""
    global _ANALYZER
    if _ANALYZER is None:
        _ANALYZER = afa.ASTFieldAnalyzer(str(_APP))
    with tempfile.TemporaryDirectory(dir=str(_APP), prefix=".tmp_afa_") as tmp:
        path = Path(tmp) / "mod.py"
        path.write_text(textwrap.dedent(source))
        return [v.field for v in _ANALYZER.validate_file(path)]


class ClassReferenceIsNotAFieldTest(unittest.TestCase):
    def test_method_on_a_class_named_like_a_doctype_is_not_a_field(self):
        found = _analyze(
            """
            from frappe.model.document import Document

            class DirectDebitBatch(Document):
                def generate_sepa_xml(self):
                    return None

                def validate(self):
                    x(DirectDebitBatch.generate_sepa_xml)
            """
        )
        self.assertNotIn("generate_sepa_xml", found)

    def test_a_class_that_is_not_named_like_a_doctype(self):
        found = _analyze(
            """
            class Foo:
                def validate(self):
                    return None

                def bar(self):
                    return None

            x(Foo.bar)
            """
        )
        self.assertEqual(found, [])

    def test_imported_class_attribute_is_not_a_field(self):
        found = _analyze(
            """
            from somewhere import Member

            def validate(self):
                return x(Member.zzz_no_such_attr)
            """
        )
        self.assertNotIn("zzz_no_such_attr", found)

    def test_control_missing_field_on_a_doc_instance_is_still_reported(self):
        found = _analyze(
            """
            import frappe

            def validate(n):
                doc = frappe.get_doc("Member", n)
                return doc.zzz_no_such_field
            """
        )
        self.assertIn("zzz_no_such_field", found)

    def test_control_class_name_rebound_to_an_instance_is_still_reported(self):
        found = _analyze(
            """
            import frappe
            from somewhere import Member

            def validate(n):
                Member = frappe.get_doc("Member", n)
                return Member.zzz_no_such_field
            """
        )
        self.assertIn("zzz_no_such_field", found)

    def test_control_instance_beside_a_same_named_class_is_still_reported(self):
        # The class `DirectDebitBatch` is exempt; an instance of the doctype in the same
        # file is not.
        found = _analyze(
            """
            import frappe
            from frappe.model.document import Document

            class DirectDebitBatch(Document):
                def generate_sepa_xml(self):
                    return None

            def validate(n):
                x(DirectDebitBatch.generate_sepa_xml)
                batch = frappe.get_doc("Direct Debit Batch", n)
                return batch.zzz_no_such_field
            """
        )
        self.assertIn("zzz_no_such_field", found)
        self.assertNotIn("generate_sepa_xml", found)


if __name__ == "__main__":
    unittest.main()
