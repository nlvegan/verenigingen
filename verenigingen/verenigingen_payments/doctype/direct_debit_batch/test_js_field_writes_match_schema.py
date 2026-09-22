"""Structural gate: direct_debit_batch.js must write field names the target
DocType actually has.

Why this needs a test at all (#1251/#1263 review):
    ``frappe.model.set_value(doctype, name, fieldname, value)`` and
    ``frm.set_value(fieldname, value)`` both silently no-op when ``fieldname``
    is not a real field on the target DocType -- no console error, no server
    round-trip failure, the value just never persists (see MEMORY.md:
    "assigning nonexistent doc field is silent no-op"). That is exactly what
    happened here TWICE with the same wrong name, ``mandate_date`` instead of
    the real field ``mandate_sign_date``:

    - :317, inside the ``invoices_add`` handler -- latent until #1251 also
      repaired the dead doctype registration it lived under.
    - :666, inside ``validate_mandates`` -- NOT gated by #1251 at all. It is
      called directly from the unconditional "Validate Mandates" button
      (shown whenever ``docstatus === 0``, no server permission gate), so this
      one was live on ``develop`` before this fix: clicking the button fetched
      the correct mandate sign date from the server and then silently failed
      to save it.

    A single corrected literal only proves that one call site; a sibling call
    with the same wrong name elsewhere in the file would pass unnoticed (as
    :666 did in the first pass of this fix). This test instead extracts every
    field name written by either call shape and checks it against the real
    DocType schema, so it generalises the gate instead of pinning one line.

Scope: every ``frappe.model.set_value(...)`` call in this file targets a row
of the ``invoices`` child table (confirmed by reading the file -- there are no
other child tables here), so those field names are checked against
``Direct Debit Batch Invoice``. Every ``frm.set_value(...)`` call targets the
parent document, checked against ``Direct Debit Batch``. If a future edit adds
a ``frappe.model.set_value`` call against some other child table in this file,
this test's single-doctype assumption would need revisiting -- the control
tests below at least catch the scan going quiet, even if they cannot catch a
wrong-doctype assumption.
"""

import os
import re

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

MODEL_SET_VALUE_PATTERN = re.compile(
    r"""frappe\.model\.set_value\(\s*[^,'"]+,\s*[^,'"]+,\s*(['"])([^'"]+)\1"""
)
FRM_SET_VALUE_PATTERN = re.compile(r"""frm\.set_value\(\s*(['"])([^'"]+)\1""")


def _js_source():
    path = os.path.join(
        frappe.get_app_path("verenigingen"),
        "verenigingen_payments",
        "doctype",
        "direct_debit_batch",
        "direct_debit_batch.js",
    )
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class TestDirectDebitBatchJsFieldWritesMatchSchema(EnhancedTestCase):
    def test_scan_finds_a_realistic_number_of_child_row_writes(self):
        """Control: if the regex silently stopped matching (e.g. the call shape
        changed), the real assertion below would vacuously pass."""
        fields = {m.group(2) for m in MODEL_SET_VALUE_PATTERN.finditer(_js_source())}
        self.assertGreater(len(fields), 3, "frappe.model.set_value scan found suspiciously few fields")

    def test_scan_finds_a_realistic_number_of_parent_writes(self):
        fields = {m.group(2) for m in FRM_SET_VALUE_PATTERN.finditer(_js_source())}
        self.assertGreater(len(fields), 3, "frm.set_value scan found suspiciously few fields")

    def test_child_row_field_writes_exist_on_direct_debit_batch_invoice(self):
        fields = {m.group(2) for m in MODEL_SET_VALUE_PATTERN.finditer(_js_source())}
        meta = frappe.get_meta("Direct Debit Batch Invoice")
        missing = sorted(f for f in fields if not meta.has_field(f))
        self.assertEqual(
            missing,
            [],
            "direct_debit_batch.js writes child-row field(s) via frappe.model.set_value "
            f"that do not exist on Direct Debit Batch Invoice (silent no-op): {missing}",
        )

    def test_parent_field_writes_exist_on_direct_debit_batch(self):
        fields = {m.group(2) for m in FRM_SET_VALUE_PATTERN.finditer(_js_source())}
        meta = frappe.get_meta("Direct Debit Batch")
        missing = sorted(f for f in fields if not meta.has_field(f))
        self.assertEqual(
            missing,
            [],
            "direct_debit_batch.js writes parent field(s) via frm.set_value that do not "
            f"exist on Direct Debit Batch (silent no-op): {missing}",
        )
