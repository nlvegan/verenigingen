"""#2478: the patch writes the missing ``require_webhook_signature`` row as 1.

Probe shortcut: the row state is built with raw ``tabSingles`` writes (that is the defect's state;
a save writes every field) and ``execute`` is called directly, not through the patch runner. The
whole row set is restored on cleanup.
"""

import importlib

import frappe
from frappe.modules import patch_handler
from frappe.tests.utils import FrappeTestCase

from verenigingen.setup import patch_fragments

DT = "Ponto Settings"
FIELD = "require_webhook_signature"
PATCH = "verenigingen.patches.v2_2.seed_ponto_webhook_signature_default_2478"


def _signature_row_2478():
    r = frappe.db.sql("select value from tabSingles where doctype=%s and field=%s", (DT, FIELD))
    return r[0][0] if r else None


class TestSeedPontoWebhookSignatureDefault(FrappeTestCase):
    def setUp(self):
        rows = frappe.db.sql("select field, value from tabSingles where doctype=%s", DT)
        self.addCleanup(self._restore_ponto_singles_2478, rows)
        # a saved Ponto Settings: rows for other fields exist
        frappe.db.sql("delete from tabSingles where doctype=%s and field=%s", (DT, "enable_webhooks"))
        frappe.db.sql("insert into tabSingles (doctype, field, value) values (%s, 'enable_webhooks', '0')", DT)

    def _restore_ponto_singles_2478(self, rows):
        frappe.db.sql("delete from tabSingles where doctype=%s", DT)
        for field, value in rows:
            frappe.db.sql("insert into tabSingles (doctype, field, value) values (%s, %s, %s)", (DT, field, value))
        frappe.clear_document_cache(DT, DT)

    @staticmethod
    def _signature_row_count_2478():
        return frappe.db.sql("select count(*) from tabSingles where doctype=%s and field=%s", (DT, FIELD))[0][0]

    def _run_seed_patch_2478(self):
        importlib.import_module(PATCH).execute()
        frappe.clear_document_cache(DT, DT)

    def test_a_missing_row_among_saved_rows_is_seeded_to_1(self):
        frappe.db.sql("delete from tabSingles where doctype=%s and field=%s", (DT, FIELD))
        self.assertEqual(frappe.get_single(DT).get(FIELD), 0, "control: the form really reads it unticked")
        self._run_seed_patch_2478()
        self.assertEqual(_signature_row_2478(), "1")
        self.assertEqual(frappe.get_single(DT).get(FIELD), 1)

    def test_an_explicit_zero_is_never_touched(self):
        frappe.db.sql("delete from tabSingles where doctype=%s and field=%s", (DT, FIELD))
        frappe.db.sql("insert into tabSingles (doctype, field, value) values (%s, %s, '0')", (DT, FIELD))
        self._run_seed_patch_2478()
        self.assertEqual(_signature_row_2478(), "0")
        self.assertEqual(self._signature_row_count_2478(), 1)

    def test_a_site_with_no_rows_is_left_to_the_declared_default(self):
        frappe.db.sql("delete from tabSingles where doctype=%s", DT)
        self._run_seed_patch_2478()
        self.assertIsNone(_signature_row_2478())

    def test_it_is_idempotent(self):
        frappe.db.sql("delete from tabSingles where doctype=%s and field=%s", (DT, FIELD))
        self._run_seed_patch_2478()
        self._run_seed_patch_2478()
        self.assertEqual(frappe.db.sql("select count(*) from tabSingles where doctype=%s and field=%s", (DT, FIELD))[0][0], 1)

    def test_the_patch_is_registered_as_a_fragment(self):
        patch_fragments.install()
        self.assertIn(PATCH, patch_handler.get_patches_from_app("verenigingen"))
