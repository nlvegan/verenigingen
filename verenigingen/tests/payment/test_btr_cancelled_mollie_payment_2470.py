"""#2470: the reconcile pool must not book a Payment Entry under a Mollie payment id whose
forward Payment Entry staff cancelled (maintainer ruling 2026-11-11, #2406).

Real documents throughout. The only stub is ``SettlementsClient``, the Mollie HTTP boundary,
where a settlement has to be fetched. The staff-cancelled entry is booked through the real
Payment Entry service and cancelled with the real ``cancel()``. It is booked for a DIFFERENT
customer than the one the pool then matches: the Payment Entry idempotency key is
(reference, type, party), so a same-party re-booking is stopped by the unique index anyway and
would not show the defect. Probe shortcut: the cancelled entry stands in for the forward
writers' entry (same reference_no, same Receive type), not a real webhook delivery.

Run:
    PYTHONPATH=<worktree> bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_btr_cancelled_mollie_payment_2470
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import flt, today

from verenigingen.tests.payment.test_bank_transaction_reconciliation import BTRBase
from verenigingen.tests.support import forward_refusal as refusal
from verenigingen.verenigingen_payments.services.payment import payment_entry_service
from verenigingen.verenigingen_payments.utils import bank_transaction_reconciliation as btr
from verenigingen.verenigingen_payments.utils import bank_transaction_status


class _CancelledMolliePaymentFixture2470(BTRBase):
    def setUp(self):
        super().setUp()
        self.payment_id = f"tr_2470_{frappe.generate_hash(length=8)}"

    def _book_forward_entry_and_staff_cancel(self):
        """A real Receive entry under the payment id for one member's invoice, then cancelled."""
        first = self._make_member_with_invoice(first_name="Fwd2470", grand_total=40.0)

        def book():
            return payment_entry_service.create_payment_entry_from_invoice(
                invoice_name=first["invoice"].name,
                amount=Decimal("40.00"),
                posting_date=today(),
                reference_no=self.payment_id,
                reference_date=today(),
                mode_of_payment="Mollie",
                payment_type="Receive",
            )

        return refusal.book_then_staff_cancel(self, self.payment_id, book)

    def _pool_candidate(self, grand_total=40.0, description_invoice=True):
        """Another member's unpaid invoice, and a DRAFT Bank Transaction (pool row) whose
        reference is the Mollie payment id and whose description names that invoice."""
        it = self._make_member_with_invoice(first_name="Pool2470", grand_total=grand_total)
        description = f"INVOICE {it['invoice'].name}" if description_invoice else "no reference"
        bt = self._make_bank_transaction(
            deposit=grand_total, description=description, reference_number=self.payment_id
        )
        return it, bt

    def _entries_for(self, invoice_name):
        return frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_doctype": "Sales Invoice", "reference_name": invoice_name, "docstatus": 1},
            pluck="parent",
        )

    def _rows_under_payment_id(self):
        return frappe.get_all(
            "Payment Entry",
            filters={"reference_no": self.payment_id, "payment_type": "Receive"},
            fields=["name", "docstatus"],
        )


class TestPoolRefusesStaffCancelledMolliePayment(_CancelledMolliePaymentFixture2470):
    def test_the_pool_does_not_book_an_invoice_match_under_a_cancelled_payment_id(self):
        cancelled = self._book_forward_entry_and_staff_cancel()
        it, bt = self._pool_candidate()

        matched = self.mgr.match_transaction(self._txn_dict(bt))

        self.assertFalse(matched)
        self.assertEqual(self._entries_for(it["invoice"].name), [], "the pool booked the invoice")
        refusal.assert_not_rebooked(self, self.payment_id, cancelled)
        refusal.assert_refused_once(self, self.payment_id, "40.00")

    def test_the_refusal_leaves_the_line_in_the_pool_not_terminally_failed(self):
        self._book_forward_entry_and_staff_cancel()
        it, bt = self._pool_candidate()

        self.assertFalse(self.mgr.match_transaction(self._txn_dict(bt)))

        bt.reload()
        self.assertNotIn(bt.custom_processing_status, bank_transaction_status.TERMINAL_OUTCOMES)
        self.assertEqual(bt.docstatus, 0)
        self.assertEqual(flt(bt.unallocated_amount), flt(bt.deposit))
        in_pool = frappe.get_all(
            "Bank Transaction", filters={**bank_transaction_status.pool_filters(), "name": bt.name}
        )
        self.assertEqual([r.name for r in in_pool], [bt.name], "the refused line left the pool")

    def test_a_redelivery_through_the_daily_pool_does_not_alert_staff_again(self):
        self._book_forward_entry_and_staff_cancel()
        it, bt = self._pool_candidate()
        for _ in range(3):
            self.assertFalse(self.mgr.match_transaction(self._txn_dict(bt)))
        refusal.assert_refused_once(self, self.payment_id, "40.00")
        self.assertEqual(self._entries_for(it["invoice"].name), [])

    def test_create_reconciliation_called_directly_refuses_too(self):
        """create_reconciliation is public: the refusal must not depend on match_transaction."""
        cancelled = self._book_forward_entry_and_staff_cancel()
        it, bt = self._pool_candidate()
        match = {
            "type": "invoice",
            "reference": it["invoice"].name,
            "confidence": 0.95,
            "match_reason": "test",
        }

        self.assertFalse(self.mgr.create_reconciliation(self._txn_dict(bt), match))

        self.assertEqual(self._entries_for(it["invoice"].name), [])
        refusal.assert_not_rebooked(self, self.payment_id, cancelled)

    def test_control_a_payment_id_never_booked_still_reconciles(self):
        """Same Mollie-style id, no Payment Entry history: the pool books it as before."""
        it, bt = self._pool_candidate()
        self.assertEqual(self._rows_under_payment_id(), [], "fixture problem: id already booked")

        self.assertTrue(self.mgr.match_transaction(self._txn_dict(bt)))

        self.assertEqual(len(self._entries_for(it["invoice"].name)), 1)
        refusal.assert_no_refusal(self, self.payment_id)

    def test_control_a_cancelled_entry_beside_a_live_one_is_not_a_refusal(self):
        """A payment that is booked (a live entry exists under the id) is not 'staff cancelled
        it': no refusal, no alert. The live entry is a real second booking for another party."""
        self._book_forward_entry_and_staff_cancel()
        other = self._make_member_with_invoice(first_name="Live2470", grand_total=40.0)
        live = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=other["invoice"].name,
            amount=Decimal("40.00"),
            posting_date=today(),
            reference_no=self.payment_id,
            reference_date=today(),
            mode_of_payment="Mollie",
            payment_type="Receive",
        )
        self.assertEqual(frappe.db.get_value("Payment Entry", live.name, "docstatus"), 1)
        it, bt = self._pool_candidate()
        self.expectErrorLog("Payment Entry Validation", "Reconciliation")

        self.mgr.match_transaction(self._txn_dict(bt))

        refusal.assert_no_refusal(self, self.payment_id)


class TestSettlementRefusesStaffCancelledMolliePayment(_CancelledMolliePaymentFixture2470):
    """The settlement path books ``reference_no = <payment id>`` per payment of a settlement."""

    def _settle(self, invoice_name, amount):
        client = MagicMock()
        client.get_payments_for_settlement.return_value = [
            {
                "id": self.payment_id,
                "metadata": {"invoice_id": invoice_name},
                "amount": {"value": f"{flt(amount):.2f}"},
            }
        ]
        bt = self._make_bank_transaction(deposit=amount, description="Mollie settlement", date=today())
        with patch.object(btr, "SettlementsClient", return_value=client):
            return self.mgr.process_mollie_settlement(
                frappe.get_doc("Bank Transaction", bt.name),
                "stl_2470",
                {"id": "stl_2470", "amount": {"value": f"{flt(amount):.2f}"}},
            )

    def test_a_settlement_does_not_book_a_payment_whose_entry_staff_cancelled(self):
        cancelled = self._book_forward_entry_and_staff_cancel()
        it = self._make_member_with_invoice(first_name="Stl2470", grand_total=40.0)

        result = self._settle(it["invoice"].name, 40.0)

        self.assertEqual(self._entries_for(it["invoice"].name), [], "the settlement booked the payment")
        self.assertEqual([d["status"] for d in result["details"]], ["refused_staff_cancelled"])
        refusal.assert_not_rebooked(self, self.payment_id, cancelled)
        refusal.assert_refused_once(self, self.payment_id, "40.00")

    def test_control_a_settlement_still_attempts_a_payment_never_booked(self):
        """Whether the booking then succeeds depends on the site's Mollie/GL currency set-up (it
        fails on a site whose company is INR), so the control asserts only what this fix owns:
        a never-booked payment is not refused and raises no alert."""
        it = self._make_member_with_invoice(first_name="StlCtl2470", grand_total=40.0)

        result = self._settle(it["invoice"].name, 40.0)

        self.assertNotIn("refused_staff_cancelled", [d["status"] for d in result["details"]])
        refusal.assert_no_refusal(self, self.payment_id)
