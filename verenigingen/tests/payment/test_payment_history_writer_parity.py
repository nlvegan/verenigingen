# Copyright (c) 2026, Veganisme.org and contributors
"""Guard against the incremental writer and the full rebuild diverging."""

import frappe

from verenigingen.services.member.payment.payment_history_service import get_payment_history_service
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# Fields compared for parity (exclude volatile/reference-metadata-only fields).
PARITY_FIELDS = [
    "invoice",
    "transaction_type",
    "reference_doctype",
    "reference_name",
    "amount",
    "outstanding_amount",
    "status",
    "payment_status",
    "payment_entry",
    "payment_method",
    "paid_amount",
    "reconciled",
    "coverage_start_date",
    "coverage_end_date",
]


class TestPaymentHistoryWriterParity(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Par", last_name="Ity")
        self.link_member_to_customer(self.member)
        self.member.reload()
        self.service = get_payment_history_service()

    def _make_submitted_invoice(self, **kwargs):
        unique = f"PAR-{frappe.generate_hash(length=8).upper()}-.#####"
        inv = self.create_test_sales_invoice(self.member.name, naming_series=unique, **kwargs)
        inv.is_membership_invoice = kwargs.get("is_membership_invoice", 0)
        inv.save()
        inv.submit()
        self.track_doc("Sales Invoice", inv.name)
        return inv

    def test_incremental_row_matches_rebuild_row(self):
        inv = self._make_submitted_invoice(is_membership_invoice=1)
        self.member.reload()

        # Rebuild path
        self.service.load_payment_history_batched(self.member)
        rebuild_row = next(r for r in self.member.payment_history if r.invoice == inv.name)

        # Incremental path
        incremental_entry = self.member._build_payment_history_entry(
            frappe.get_doc("Sales Invoice", inv.name)
        )

        for field in PARITY_FIELDS:
            self.assertEqual(
                incremental_entry.get(field),
                rebuild_row.get(field),
                f"Divergence on '{field}': incremental={incremental_entry.get(field)!r} "
                f"rebuild={rebuild_row.get(field)!r}",
            )

    def test_reconciling_pe_flips_invoice_row_to_paid(self):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        inv = self._make_submitted_invoice(is_membership_invoice=1)
        pe = get_payment_entry("Sales Invoice", inv.name)
        pe.reference_no = "PARITY-PE"
        pe.reference_date = frappe.utils.today()
        pe.save()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)

        self.member.reload()
        entry = self.member._build_payment_history_entry(frappe.get_doc("Sales Invoice", inv.name))
        self.assertEqual(entry["payment_status"], "Paid")
        self.assertEqual(entry["reconciled"], 1)
        self.assertEqual(entry["transaction_type"], "Membership Invoice")
