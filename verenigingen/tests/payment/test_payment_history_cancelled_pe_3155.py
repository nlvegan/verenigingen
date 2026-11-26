# Copyright (c) 2026, Veganisme.org and contributors
"""#3155: payment history must count only SUBMITTED Payment Entries as paid.

A cancelled (docstatus 2) or draft (docstatus 0) Payment Entry is not money received.
Both history writers (incremental builder and batch rebuild) summed every Payment Entry
Reference of the invoice, so an invoice whose payment was cancelled kept paid_amount at
the full amount while its outstanding_amount was back to the full amount.

Real Sales Invoice, real Payment Entry, real cancel; no field is set directly.
"""

import frappe
from frappe.utils import flt, today

from verenigingen.services.member.payment.payment_history_service import get_payment_history_service
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentHistoryIgnoresNonSubmittedPE3155(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Cxl", last_name="PaidHist")
        self.link_member_to_customer(self.member)
        self.member.reload()
        self.service = get_payment_history_service()

    def _t3155_invoice(self):
        series = f"T3155-{frappe.generate_hash(length=8).upper()}-.#####"
        inv = self.create_test_sales_invoice(self.member.name, naming_series=series, status="Draft")
        inv.submit()
        self.track_doc("Sales Invoice", inv.name)
        return inv

    def _t3155_pe(self, invoice, amount=None, submit=True):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry("Sales Invoice", invoice.name)
        pe.reference_no = f"T3155-{frappe.generate_hash(length=6)}"
        pe.reference_date = today()
        if amount is not None:
            pe.paid_amount = amount
            pe.received_amount = amount
            pe.references[0].allocated_amount = amount
        pe.save()
        if submit:
            pe.submit()
        self.track_doc("Payment Entry", pe.name)
        return pe

    def _t3155_rows(self, invoice_name):
        """(incremental row, rebuild row) for one invoice."""
        incremental = self.member._build_payment_history_entry(frappe.get_doc("Sales Invoice", invoice_name))
        self.member.reload()
        self.service.load_payment_history_batched(self.member)
        rebuild = next(r for r in self.member.payment_history if r.invoice == invoice_name)
        return incremental, rebuild

    def test_cancelled_pe_does_not_count_as_paid(self):
        inv = self._t3155_invoice()
        pe = self._t3155_pe(inv)
        pe.cancel()
        inv.reload()
        self.assertEqual(
            flt(inv.outstanding_amount), flt(inv.grand_total), "fixture: cancel must reopen the invoice"
        )
        # The cancelled PE's reference row must really still exist, or this proves nothing.
        self.assertTrue(
            frappe.db.exists("Payment Entry Reference", {"parent": pe.name, "reference_name": inv.name})
        )
        for label, row in zip(("incremental", "rebuild"), self._t3155_rows(inv.name)):
            self.assertEqual(flt(row.get("paid_amount")), 0, f"{label}: paid_amount")
            self.assertFalse(row.get("reconciled"), f"{label}: reconciled")
            self.assertFalse(row.get("payment_entry"), f"{label}: payment_entry")
            self.assertEqual(row.get("payment_status"), "Unpaid", f"{label}: payment_status")

    def test_draft_pe_does_not_count_as_paid(self):
        inv = self._t3155_invoice()
        self._t3155_pe(inv, submit=False)
        for label, row in zip(("incremental", "rebuild"), self._t3155_rows(inv.name)):
            self.assertEqual(flt(row.get("paid_amount")), 0, f"{label}: paid_amount")
            self.assertFalse(row.get("reconciled"), f"{label}: reconciled")
            self.assertFalse(row.get("payment_entry"), f"{label}: payment_entry")

    def test_live_pe_still_counts_as_paid(self):
        """Control: a submitted PE is paid (a real row for a wrong 'nothing counts' fix to hit)."""
        inv = self._t3155_invoice()
        pe = self._t3155_pe(inv)
        for label, row in zip(("incremental", "rebuild"), self._t3155_rows(inv.name)):
            self.assertEqual(flt(row.get("paid_amount")), flt(inv.grand_total), f"{label}: paid_amount")
            self.assertTrue(row.get("reconciled"), f"{label}: reconciled")
            self.assertEqual(row.get("payment_entry"), pe.name, f"{label}: payment_entry")
            self.assertEqual(row.get("payment_status"), "Paid", f"{label}: payment_status")

    def test_only_the_live_part_payment_counts_next_to_a_cancelled_one(self):
        inv = self._t3155_invoice()
        half = flt(inv.grand_total) / 2
        cancelled = self._t3155_pe(inv, amount=half)
        cancelled.cancel()
        live = self._t3155_pe(inv, amount=half)
        for label, row in zip(("incremental", "rebuild"), self._t3155_rows(inv.name)):
            self.assertEqual(flt(row.get("paid_amount")), half, f"{label}: paid_amount")
            self.assertEqual(row.get("payment_entry"), live.name, f"{label}: payment_entry")
            self.assertEqual(row.get("payment_status"), "Partially Paid", f"{label}: payment_status")

    def test_cancelled_part_payment_does_not_make_invoice_partially_paid(self):
        """determine_payment_status's `0 < paid_amount < grand_total` branch is where a
        stale paid_amount changes the member-facing status (develop: 'Partially Paid' on an
        invoice that is back to Unpaid with full outstanding)."""
        inv = self._t3155_invoice()
        self._t3155_pe(inv, amount=flt(inv.grand_total) / 2).cancel()
        inv.reload()
        self.assertEqual(flt(inv.outstanding_amount), flt(inv.grand_total))
        self.assertEqual(inv.status, "Unpaid")
        for label, row in zip(("incremental", "rebuild"), self._t3155_rows(inv.name)):
            self.assertEqual(row.get("payment_status"), "Unpaid", f"{label}: payment_status")
