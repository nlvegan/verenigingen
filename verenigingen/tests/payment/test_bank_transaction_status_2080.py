"""#2080: ERPNext owns Bank Transaction.status (version-16 7526af9b2).

A DRAFT is reset to "Pending" on every save; a SUBMITTED row's status is derived from
``unallocated_amount``. ``persist_draft_status`` must therefore survive a save on a draft
(the app's retry-pool contract) and must NOT override ERPNext's derivation on a submitted row.
"""

from frappe.utils import today

from verenigingen.tests.payment.test_bank_transaction_reconciliation import BTRBase
from verenigingen.verenigingen_payments.utils.bank_transaction_status import persist_draft_status


class TestPersistDraftStatus(BTRBase):
    def test_draft_status_survives_save_then_persist(self):
        bt = self._make_bank_transaction(deposit=12.0, date=today())
        self.assertEqual(bt.docstatus, 0)
        bt.add_comment("Comment", "x")
        bt.save()
        self.assertEqual(bt.status, "Pending", "ERPNext resets a draft to Pending on save")
        persist_draft_status(bt, "Reconciled")
        bt.reload()
        self.assertEqual(bt.status, "Reconciled")

    def test_submitted_status_stays_derived_by_erpnext(self):
        bt = self._make_bank_transaction(deposit=12.0, date=today(), submit=True)
        self.assertEqual(bt.docstatus, 1)
        self.assertEqual(bt.status, "Unreconciled")
        persist_draft_status(bt, "Reconciled")
        bt.reload()
        self.assertEqual(bt.status, "Unreconciled", "unallocated_amount > 0, so ERPNext says Unreconciled")
