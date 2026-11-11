"""
#2406 (F2): the orphan Payment Entry writer must refuse a payment whose forward entry staff cancelled.

``MolliePaymentOrchestrator._create_orphan_payment_entry`` is the eighth writer of a Receive Payment
Entry carrying a Mollie payment id. It reaches the same harm as the other seven: with the SAME party
the cancelled row's unique key makes the insert fail (swallowed as "partial", no alert); with a
DIFFERENT party the key differs, so the payment is booked again. Maintainer ruling 2026-11-11: refuse,
log, alert, acknowledge.

Real writers, real Payment Entry, real Staff Alert Event and Error Log rows.

Run:
    PYTHONPATH=<worktree> bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_orphan_forward_refusal_2406
"""

from types import SimpleNamespace

import frappe
from frappe.utils import today

from verenigingen.tests.payment.test_mollie_orchestrator_coverage_b2 import OrchestratorBase
from verenigingen.tests.support import forward_refusal as refusal
from verenigingen.tests.support.mollie_settings import (
    pin_mollie_clearing_account,
    pin_payments_settings,
    pin_verenigingen_settings,
)
from verenigingen.verenigingen_payments.mollie.tests.fixtures.payment_entry_fixtures import (
    ensure_mollie_bank_gl_account,
)

AMOUNT = 25.0


class TestOrphanForwardRefusal(OrchestratorBase):
    def setUp(self):
        super().setUp()
        from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
            MolliePaymentOrchestrator,
        )

        self.orch = MolliePaymentOrchestrator()
        clearing = ensure_mollie_bank_gl_account(self.company)
        self.assertTrue(clearing, "fixture problem: no Mollie clearing account")
        pin_verenigingen_settings(self, company=self.company)
        pin_mollie_clearing_account(self, clearing)
        # The orphan invoice reads this Single; a stale value from a co-tenant names another company.
        pin_payments_settings(self, dues_income_account=self._get_or_create_income_account(self.company))
        self.member = self._make_member_with_customer(first_name="OrphanRefuse")
        self.other_member = self._make_member_with_customer(first_name="OrphanOther")
        self.invoice = self._make_sales_invoice(self.member.customer, today(), today(), outstanding=AMOUNT)
        self.other_invoice = self._make_sales_invoice(
            self.other_member.customer, today(), today(), outstanding=AMOUNT
        )

    def _write_orphan_entry(self, other_party=False):
        """Book through the real writer: for the member, or for ANOTHER party (own invoice)."""
        member, invoice = (self.other_member, self.other_invoice) if other_party else (self.member, self.invoice)
        return self.orch._create_orphan_payment_entry(
            payment_id=self.pid,
            customer=member.customer,
            invoice_name=invoice.name,
            amount=AMOUNT,
            payment_date=today(),
        )

    def _orphan_rows_2406(self, **extra):
        filters = {"reference_no": self.pid, "payment_type": "Receive", **extra}
        return frappe.get_all("Payment Entry", filters=filters, fields=["name", "docstatus", "party"])

    def _cancelled_row_of_another_party(self):
        """A CANCELLED Receive row for this payment id, beside the live one already booked."""
        other = self._write_orphan_entry(other_party=True)
        self.assertTrue(other, "fixture problem: second row not booked")
        frappe.get_doc("Payment Entry", other).cancel()
        self.assertEqual(frappe.db.get_value("Payment Entry", other, "docstatus"), 2)

    def test_same_party_redelivery_is_refused_and_alerts(self):
        first = refusal.book_then_staff_cancel(self, self.pid, self._write_orphan_entry)
        self.assertIsNone(self._write_orphan_entry())
        refusal.assert_not_rebooked(self, self.pid, first)
        refusal.assert_refused_once(self, self.pid, "25.00")
        self.assertIsNone(self._write_orphan_entry())  # a second redelivery stays refused, no second alert
        refusal.assert_refused_once(self, self.pid, "25.00")

    def test_different_party_redelivery_is_refused_not_rebooked(self):
        """The key hashes the party, so a different party is NOT stopped by the unique index."""
        first = refusal.book_then_staff_cancel(self, self.pid, self._write_orphan_entry)
        self.assertIsNone(self._write_orphan_entry(other_party=True))
        refusal.assert_not_rebooked(self, self.pid, first)
        refusal.assert_refused_once(self, self.pid, "25.00")

    def test_control_first_delivery_books_and_raises_no_refusal(self):
        pe = self._write_orphan_entry()
        self.assertTrue(pe)
        self.assertEqual([r.name for r in self._orphan_rows_2406(docstatus=1)], [pe])
        refusal.assert_no_refusal(self, self.pid)

    # -- the whole flow: a refused payment must not leave a new orphan invoice behind ----------

    def _orphan_payment_stub(self):
        return SimpleNamespace(
            id=self.pid,
            status="paid",
            amount={"value": f"{AMOUNT:.2f}", "currency": "EUR"},
            paid_at=f"{today()}T10:05:00+00:00",
            created_at=f"{today()}T10:00:00+00:00",
            description="orphan 2406",
            method="ideal",
            metadata={},
        )

    def _orphan_invoices(self):
        return frappe.db.count("Sales Invoice", {"remarks": ["like", f"%{self.pid}%"]})

    def test_flow_redelivery_after_staff_cancel_is_refused_before_any_new_document(self):
        first = self.orch.process_orphaned_payment_with_invoice(self.pid, self._orphan_payment_stub())
        self.assertEqual(first.status, "success", f"fixture problem: {first.error}")
        frappe.get_doc("Payment Entry", first.payment_entry).cancel()
        refusal.prepare_refusal_fixture(self, self.pid)
        invoices_before = self._orphan_invoices()

        result = self.orch.process_orphaned_payment_with_invoice(self.pid, self._orphan_payment_stub())

        self.assertEqual(result.status, "skipped", result.error)
        self.assertEqual(self._orphan_rows_2406(docstatus=["!=", 2]), [])
        self.assertEqual(self._orphan_invoices(), invoices_before, "a refused payment created an invoice")
        refusal.assert_refused_once(self, self.pid, "25.00")
        self.orch.process_orphaned_payment_with_invoice(self.pid, self._orphan_payment_stub())
        refusal.assert_refused_once(self, self.pid, "25.00")

    def test_flow_control_cancelled_row_beside_a_live_one_is_not_a_refusal(self):
        """A cancelled Receive row AND a live one for the payment: booked, so nothing to refuse.

        End-to-end control only: the flow returns 'skipped' on the live entry
        (get_processing_status) before the guard is reached, so this does NOT discriminate the
        refuse-on-any-cancelled-row mutant. The writer-level control below does."""
        live = self._write_orphan_entry()
        self.assertTrue(live)
        self._cancelled_row_of_another_party()
        refusal.prepare_refusal_fixture(self, self.pid)

        result = self.orch.process_orphaned_payment_with_invoice(self.pid, self._orphan_payment_stub())

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.payment_entry, live, "the live entry should be what was found")
        refusal.assert_no_refusal(self, self.pid)

    def test_writer_control_cancelled_row_beside_a_live_one_is_not_a_refusal(self):
        live = self._write_orphan_entry()
        self._cancelled_row_of_another_party()
        refusal.prepare_refusal_fixture(self, self.pid)
        self.expectErrorLog("Orphan PE Creation Error")  # the invoice is already paid by the live row
        self._write_orphan_entry()  # same party as the live row: the unique key stops it, but it is NOT a refusal
        refusal.assert_no_refusal(self, self.pid)
