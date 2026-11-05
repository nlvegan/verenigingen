"""#2082: the reconcile pool keys on an app-owned marker, not on Bank Transaction.status.

ERPNext owns ``status`` (erpnext version-16 7526af9b2: every save of a DRAFT resets it to
"Pending"). The app used to stamp "Reconciled"/"Unreconciled" onto a draft to take it out of
``reconcile_bank_transactions``' pool, and that stamp was undone by the draft's next ordinary
save, after which the pool picked the row up again.

Maintainer ruling (2026-11-05): follow ERPNext's model. The app does not write ``status``; the
pool's outcome lives in ``custom_processing_status``, and the pool takes in drafts only.
"""

import frappe
from frappe.utils import flt, today

from verenigingen.tests.e_boekhouden.test_payment_processor_sweep import _PayProcBase
from verenigingen.tests.payment.test_bank_transaction_reconciliation import BTRBase
from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
    get_reconciliation_summary,
)


class TestReconcilePoolAppOwnedMarker(BTRBase):
    def _run_pool(self):
        return self.mgr.reconcile_bank_transactions(
            bank_account=self._eur_bank_account, from_date=today(), to_date=today()
        )

    def _comments(self, bt, containing):
        return [
            c
            for c in frappe.get_all(
                "Comment",
                filters={"reference_doctype": "Bank Transaction", "reference_name": bt.name},
                pluck="content",
            )
            if containing in (c or "")
        ]

    def _ordinary_save(self, bt):
        """What Desk, other app code or ERPNext does to a draft: load it and save it."""
        doc = frappe.get_doc("Bank Transaction", bt.name)
        doc.description = (doc.description or "") + " "
        doc.save()
        self.assertEqual(doc.status, "Pending", "ERPNext resets a draft to Pending on save")

    def _reconciled_draft(self, first_name):
        it = self._make_member_with_invoice(first_name=first_name, grand_total=30.0)
        bt = self._make_bank_transaction(deposit=30.0, description=f"INVOICE {it['invoice'].name}")
        self._run_pool()
        self.assertEqual(len(self._comments(bt, "Auto-reconciled")), 1, "fixture: the pool booked it")
        return it, bt

    def _failed_draft(self, first_name):
        it = self._make_member_with_invoice(first_name=first_name, grand_total=30.0)
        # A deposit above the outstanding is refused by the invoice path.
        bt = self._make_bank_transaction(deposit=500.0, description=f"INVOICE {it['invoice'].name}")
        self.expectErrorLog("Payment Entry Validation")
        self._run_pool()
        self.assertEqual(len(self._comments(bt, "Reconciliation failed")), 1, "fixture: the pool refused it")
        return it, bt

    # ---- the #2082 defect ------------------------------------------------------------

    def test_a_reconciled_draft_stays_out_of_the_pool_after_an_ordinary_save(self):
        it, bt = self._reconciled_draft("P2082Rec")
        self._ordinary_save(bt)

        self._run_pool()

        self.assertEqual(
            self._comments(bt, "Reconciliation failed"),
            [],
            "the pool picked a reconciled draft up again after an ordinary save",
        )
        self.assertEqual(len(self._comments(bt, "Auto-reconciled")), 1)

    def test_a_failed_draft_stays_out_of_the_pool_after_an_ordinary_save(self):
        it, bt = self._failed_draft("P2082Fail")
        self._ordinary_save(bt)

        self._run_pool()

        self.assertEqual(
            len(self._comments(bt, "Reconciliation failed")),
            1,
            "the pool picked a failed draft up again after an ordinary save",
        )

    # ---- the app leaves status to ERPNext ----------------------------------------------

    def test_a_reconciled_draft_keeps_erpnext_status_and_carries_the_marker(self):
        it, bt = self._reconciled_draft("P2082RecM")
        bt.reload()
        self.assertEqual(bt.status, "Pending", "the app must not write Bank Transaction.status")
        self.assertEqual(bt.custom_processing_status, "Fully Reconciled")

    def test_a_failed_draft_keeps_erpnext_status_and_carries_the_marker(self):
        it, bt = self._failed_draft("P2082FailM")
        bt.reload()
        self.assertEqual(bt.status, "Pending", "the app must not write Bank Transaction.status")
        self.assertEqual(bt.custom_processing_status, "Reconciliation Failed")

    # ---- controls: what must NOT change ------------------------------------------------

    def test_a_draft_labelled_for_retry_is_still_taken_in(self):
        """"Partial - Manual Review Required" is the settlement branch's RETRY label: such a
        draft stays in the pool (bounded by MAX_SETTLEMENT_RETRIES). Only terminal outcomes
        leave it."""
        it = self._make_member_with_invoice(first_name="P2082Retry", grand_total=30.0)
        bt = self._make_bank_transaction(deposit=30.0, description=f"INVOICE {it['invoice'].name}")
        bt.db_set("custom_processing_status", "Partial - Manual Review Required", update_modified=False)

        self._run_pool()

        self.assertEqual(len(self._comments(bt, "Auto-reconciled")), 1, "a retry-labelled draft was skipped")
        it["invoice"].reload()
        self.assertEqual(flt(it["invoice"].outstanding_amount), 0.0)

    def test_a_submitted_unreconciled_row_is_not_taken_in(self):
        """Ruling: drafts only. A submitted row ERPNext calls "Unreconciled" belongs to
        ERPNext's Bank Reconciliation Tool, not to this pool."""
        it = self._make_member_with_invoice(first_name="P2082Sub", grand_total=30.0)
        bt = self._make_bank_transaction(
            deposit=30.0, description=f"INVOICE {it['invoice'].name}", submit=True
        )
        self.assertEqual(bt.status, "Unreconciled")

        self._run_pool()

        self.assertEqual(self._comments(bt, "Auto-reconciled"), [])
        it["invoice"].reload()
        self.assertEqual(flt(it["invoice"].outstanding_amount), 30.0)

    def test_the_summary_counts_a_pool_reconciled_draft_as_reconciled(self):
        before = get_reconciliation_summary(from_date=today(), to_date=today())
        self._reconciled_draft("P2082Sum")
        after = get_reconciliation_summary(from_date=today(), to_date=today())
        self.assertEqual(after["reconciled"] - before["reconciled"], 1)
        self.assertEqual(after["pending"] - before["pending"], 0)


class TestEBoekhoudenReimportOfAReconciledDraft(_PayProcBase):
    """The e-boekhouden importer's "already reconciled" guard read a draft's status the same way."""

    def _draft_bt(self, ref, amount):
        bt = frappe.new_doc("Bank Transaction")
        bt.update(
            {
                "date": today(),
                "bank_account": self.bank_account,
                "company": self.company,
                "deposit": amount,
                "withdrawal": 0,
                "currency": "EUR",
                "reference_number": ref,
                "description": "eb 2082",
                "unallocated_amount": amount,
                "allocated_amount": 0,
            }
        )
        bt.insert()
        return bt

    def _je(self, amount, mut_id=None):
        je = frappe.new_doc("Journal Entry")
        je.update({"company": self.company, "posting_date": today(), "cheque_date": today()})
        je.cheque_no = f"EB-2082-{frappe.generate_hash(length=6)}"
        if mut_id:
            je.eboekhouden_mutation_nr = str(mut_id)
        je.append("accounts", {"account": self.bank, "debit_in_account_currency": amount, "cost_center": self.cost_center})
        je.append("accounts", {"account": self.income, "credit_in_account_currency": amount, "cost_center": self.cost_center})
        je.insert()
        je.submit()
        return je

    def test_a_reimport_does_not_link_a_second_journal_entry_to_a_reconciled_draft(self):
        mut_id = 7820821
        p = self._processor()
        bt = self._draft_bt(f"EB-{mut_id}", 40.0)
        first = self._je(40.0, mut_id)
        p._link_bank_transaction_to_journal_entry(bt.name, first.name, 40.0)
        # An ordinary save: ERPNext resets the draft to "Pending".
        doc = frappe.get_doc("Bank Transaction", bt.name)
        doc.description += " "
        doc.save()

        second = self._je(40.0)
        p._create_bank_transaction_for_journal_entry(
            {"id": mut_id, "type": 5, "description": "re-import"}, second, self.bank, self.bank_account
        )

        linked = frappe.get_all(
            "Bank Transaction Payments", filters={"parent": bt.name}, pluck="payment_entry"
        )
        self.assertEqual(linked, [first.name], "a reconciled draft was linked to a second Journal Entry")
