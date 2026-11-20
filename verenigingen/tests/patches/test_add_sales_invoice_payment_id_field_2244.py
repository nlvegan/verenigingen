# Copyright (c) 2026, Verenigingen
# License: MIT

"""The Sales Invoice.payment_id Custom Field (#2244): defined as ruled, the patch is a no-op where it
exists and is registered as a post_model_sync fragment. The fixture carries the same definition,
so a fresh install (which skips patches) gets it too."""

import json
from pathlib import Path

import frappe
from frappe.modules import patch_handler

from verenigingen.patches.v2_2 import add_sales_invoice_payment_id_field_2244 as patch
from verenigingen.setup import patch_fragments
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

FIELD = "Sales Invoice-payment_id"


class TestSalesInvoicePaymentIdField2244(EnhancedTestCase):
    def test_the_field_exists_as_ruled_and_the_patch_is_a_no_op_on_it(self):
        """Not tested by deleting the field first: dropping a Custom Field alters the table, which
        commits, so the harness rollback could not restore the row and every later test in the
        shard would lose the field. The create path is the framework's own ``create_custom_field``."""
        patch.execute()
        patch.execute()

        field = frappe.get_meta("Sales Invoice").get_field("payment_id")
        self.assertIsNotNone(field)
        self.assertEqual((field.fieldtype, field.no_copy, field.read_only, field.allow_on_submit), ("Data", 1, 1, 1))
        self.assertEqual(frappe.db.count("Custom Field", {"dt": "Sales Invoice", "fieldname": "payment_id"}), 1)
        self.assertEqual(field.unique, 0, "ruling #2244: no unique index")

    def test_the_fixture_defines_the_same_field(self):
        fixture = Path(frappe.get_app_path("verenigingen", "fixtures", "custom_field.json"))
        rows = [r for r in json.loads(fixture.read_text()) if r.get("name") == FIELD]
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            (rows[0]["fieldtype"], rows[0]["no_copy"], rows[0]["allow_on_submit"], rows[0]["unique"]),
            ("Data", 1, 1, 0),
        )

    def test_the_patch_is_registered_as_a_post_model_sync_fragment(self):
        patch_fragments.install()
        registered = patch_handler.get_patches_from_app("verenigingen")
        self.assertIn("verenigingen.patches.v2_2.add_sales_invoice_payment_id_field_2244", registered)
