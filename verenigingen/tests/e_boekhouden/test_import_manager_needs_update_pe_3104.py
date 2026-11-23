"""
#3104: ``EBoekhoudenImportManager._needs_update`` must not call an UNCHANGED imported
Payment Entry "changed".

It used to compare ``doc.remarks != mutation["description"]``. A Payment Entry's stored
remarks is never the bare description (ERPNext's ``set_remarks`` text, or the importer's
multi-line audit text), so every imported Payment Entry read "needs update" and
``_update_document`` cancelled, deleted and re-imported it.

The Payment Entries here come from the importer itself (``_create_payment_entry``), not
from a hand-built document, so the stored remarks are whatever the importer really writes.

Run with:
    bench --site test_site_6 run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_import_manager_needs_update_pe_3104
"""

import copy

import frappe
from frappe.utils import add_days, today

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import _create_payment_entry
from verenigingen.e_boekhouden.utils.import_manager import EBoekhoudenImportManager
from verenigingen.tests.e_boekhouden.test_rest_migration_payments import (
    BANK_LEDGER,
    INCOME_LEDGER,
    _PaymentTestBase,
)


class TestNeedsUpdatePaymentEntry3104(_PaymentTestBase):
    def setUp(self):
        super().setUp()
        self._orig_default_company = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
        frappe.db.set_single_value("E-Boekhouden Settings", "default_company", self.company)
        self.mutation = {
            "id": self._uid(),
            "type": 3,
            "date": today(),
            "amount": 125.0,
            "ledgerId": BANK_LEDGER,
            "relationId": "REL-CUST-1",
            "invoiceNumber": "",
            "description": "needs-update 3104 receipt",
            "rows": [{"ledgerId": INCOME_LEDGER, "amount": 125.0, "description": "row"}],
        }
        pe = _create_payment_entry(self.mutation, self.company, self.cost_center, [])
        self.doc_info = {"doctype": "Payment Entry", "name": pe.name}

    def tearDown(self):
        frappe.db.set_single_value("E-Boekhouden Settings", "default_company", self._orig_default_company)
        super().tearDown()

    def _needs(self, mutation):
        return EBoekhoudenImportManager()._needs_update(self.doc_info, mutation)

    def test_unchanged_mutation_is_not_a_needs_update(self):
        self.assertFalse(self._needs(copy.deepcopy(self.mutation)))

    def test_changed_row_amount_needs_update(self):
        changed = copy.deepcopy(self.mutation)
        changed["amount"] = 130.0
        changed["rows"][0]["amount"] = 130.0
        self.assertTrue(self._needs(changed))

    def test_changed_date_needs_update(self):
        changed = copy.deepcopy(self.mutation)
        changed["date"] = add_days(today(), -1)
        self.assertTrue(self._needs(changed))

    def test_stored_amount_is_compared_to_the_row_total_not_the_top_level_amount(self):
        # The importer treats rows as the source of truth (top-level amount is only a
        # fallback), so a stale top-level amount alone must not trigger a re-import.
        same_rows = copy.deepcopy(self.mutation)
        same_rows["amount"] = 999.0
        self.assertFalse(self._needs(same_rows))

    def test_no_rows_falls_back_to_the_top_level_amount(self):
        # Control for the fallback branch: with no rows the top-level amount decides.
        no_rows = copy.deepcopy(self.mutation)
        no_rows["rows"] = []
        self.assertFalse(self._needs(no_rows))
        no_rows["amount"] = 130.0
        self.assertTrue(self._needs(no_rows))
