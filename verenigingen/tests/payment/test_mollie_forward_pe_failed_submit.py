"""
#2406: a forward (Receive) Mollie Payment Entry whose submit fails must leave nothing behind.

Sibling of #2384 (refunds). Real writers, real Payment Entry; the only stub is a submit-time
failure injected on ``PaymentEntry`` (before posting: ``submit`` raises, leaving a draft;
after docstatus 1 is written: ``on_submit`` raises, the GL post never happened).
Assertions read the ``Payment Entry`` table: a retry must be able to book the payment.

Run:
    PYTHONPATH=<worktree> bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_forward_pe_failed_submit
"""

from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_mollie_reversal_single_booking import (
    _ensure_mollie_named_bank_account,
)
from verenigingen.tests.services.test_donation_refund_journal_entry_creator_coverage import (
    COMPANY,
    _RefundFixtureMixin,
)
from verenigingen.tests.support.mollie_settings import (
    pin_mollie_clearing_account,
    pin_verenigingen_settings,
)
from verenigingen.verenigingen_payments.mollie.api.payment_webhook import create_payment_entry_for_donation
from verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator import (
    create_unified_payment_entry,
)


class TestForwardPaymentEntryFailedSubmit(_RefundFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.ensure_mode_of_payment("Mollie", "Bank")
        self.clearing_account = self._ensure_clearing_account()
        self.income_account = self._ensure_income_account()
        self.bank_account = self._ensure_bank_account(self.clearing_account)
        _ensure_mollie_named_bank_account()
        self.receivable = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
        )
        pin_verenigingen_settings(self, company=COMPANY, donation_receivable_account=self.receivable)
        pin_mollie_clearing_account(self, self.clearing_account)
        self.donor = self._make_donor()
        self.customer = frappe.get_doc("Donor", self.donor).get_or_create_customer()
        self.payment_id = f"tr_fwd_{frappe.generate_hash(length=8)}"
        self.donation = self._make_donation(self.donor, 100.0)
        frappe.db.set_value("Donation", self.donation.name, "payment_id", self.payment_id)
        self.donation.payment_id = self.payment_id

    # -- helpers ---------------------------------------------------------------------------

    def _rows(self, **extra):
        filters = {"reference_no": self.payment_id, "payment_type": "Receive", **extra}
        return frappe.get_all("Payment Entry", filters=filters, fields=["name", "docstatus"])

    def _fail_submit(self, how):
        if how == "before_posting":
            return patch.object(PaymentEntry, "submit", side_effect=frappe.ValidationError("period closed"))
        return patch.object(PaymentEntry, "on_submit", side_effect=frappe.ValidationError("bad account"))

    def _assert_booked_once(self, pe):
        self.assertIsNotNone(pe, "the retry did not book the payment")
        self.assertEqual(frappe.db.get_value("Payment Entry", pe.name, "docstatus"), 1)
        self.assertEqual([r.name for r in self._rows(docstatus=1)], [pe.name])
        live_gl = frappe.db.count(
            "GL Entry", {"voucher_type": "Payment Entry", "voucher_no": pe.name, "is_cancelled": 0}
        )
        self.assertGreater(live_gl, 0, "the booked Payment Entry posted no GL rows")

    def _webhook_data(self):
        return {"payment_id": self.payment_id, "method": "ideal"}

    # -- webhook writer (payment_webhook.create_payment_entry_for_donation) ----------------

    def _webhook_fails_then_retries(self, how):
        self.expectErrorLog("Payment Entry Creation")
        with self._fail_submit(how):
            self.assertIsNone(create_payment_entry_for_donation(self.donation, self._webhook_data()))
        self.assertEqual(self._rows(), [], "the failed webhook submit left a row claiming the payment")
        self._assert_booked_once(create_payment_entry_for_donation(self.donation, self._webhook_data()))

    def test_webhook_failed_submit_before_posting_leaves_no_draft(self):
        self._webhook_fails_then_retries("before_posting")

    def test_webhook_failed_submit_after_docstatus_written_leaves_no_row(self):
        self._webhook_fails_then_retries("on_submit")

    # -- dues writer (DuesPaymentProcessor._create_unallocated_payment_entry) ---------------

    def _unallocated_kwargs(self):
        return {
            "customer": self.customer,
            "company": COMPANY,
            "clearing_account": self.clearing_account,
            "amount": 25.0,
            "payment_id": self.payment_id,
            "payment_date": today(),
            "mode_of_payment": "Mollie",
            "member_name": None,
            "remarks": "dues",
        }

    def _dues_fails_then_retries(self, how):
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        processor = DuesPaymentProcessor()
        with self._fail_submit(how), self.assertRaises(frappe.ValidationError):
            processor._create_unallocated_payment_entry(**self._unallocated_kwargs())
        self.assertEqual(self._rows(), [], "the failed dues submit left a row claiming the payment")
        self._assert_booked_once(processor._create_unallocated_payment_entry(**self._unallocated_kwargs()))

    def test_dues_failed_submit_before_posting_leaves_no_draft(self):
        self._dues_fails_then_retries("before_posting")

    def test_dues_failed_submit_after_docstatus_written_leaves_no_row(self):
        self._dues_fails_then_retries("on_submit")

    # -- unified creator, Receive (lookup had no docstatus filter) --------------------------

    def _unified(self):
        return create_unified_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            amount=100.0,
            payment_type="Receive",
        )

    def test_unified_receive_retry_after_failed_submit_books_a_new_entry(self):
        self.expectErrorLog("Unified Payment Entry Creation")
        with self._fail_submit("on_submit"):
            self.assertIsNone(self._unified())
        self.assertEqual(self._rows(docstatus=["!=", 2]), [], "a failed submit left a live Receive row")
        pe = self._unified()
        self.assertIsNotNone(pe, "the retry was handed the failed attempt as 'already exists'")
        self.assertEqual(frappe.db.get_value("Payment Entry", pe.name, "docstatus"), 1)

    # -- factory (delete_doc cannot remove a row already written as docstatus 1) ------------

    def test_factory_failed_on_submit_leaves_no_row_and_retry_books(self):
        from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import (
            PaymentContext,
        )
        from verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory import (
            PaymentEntryFactory,
        )

        context = PaymentContext("donation", "Donation", self.donation.name)
        data = {"payment_id": self.payment_id, "amount": "100.00"}
        factory = PaymentEntryFactory()
        self.expectErrorLog("Payment Entry")
        with self._fail_submit("on_submit"):
            self.assertIsNone(factory.create_payment_entry(context, data, customer=self.customer))
        self.assertEqual(self._rows(docstatus=["!=", 2]), [], "the failed submit left a live row")
        pe = factory.create_payment_entry(context, data, customer=self.customer)
        self._assert_booked_once(pe)

    # -- a staff-cancelled forward entry is not a booking: a redelivery must book anew -------

    def _book_then_staff_cancel(self, book):
        first = book()
        self.assertIsNotNone(first, "fixture problem: payment not booked")
        frappe.get_doc("Payment Entry", first.name).cancel()
        self.assertEqual(self._rows(docstatus=1), [], "fixture problem: cancel left a live row")
        return first

    def _assert_one_new_live_entry(self, first, second):
        self.assertIsNotNone(second, "the redelivery after a staff cancel did not book")
        self.assertNotEqual(second.name, first.name)
        self._assert_booked_once(second)

    def test_redelivery_after_staff_cancel_books_one_new_entry_end_to_end(self):
        """Real flow through process_successful_payment_with_idempotency, using the real
        idempotency check (which counts submitted entries only, so it reports 'not created')."""
        from types import SimpleNamespace

        from verenigingen.verenigingen_payments.mollie.api.payment_webhook import (
            check_payment_processing_status,
            process_successful_payment_with_idempotency,
        )

        payment = SimpleNamespace(
            id=self.payment_id,
            status="paid",
            amount={"value": "100.00", "currency": "EUR"},
            method="ideal",
            customer_id=None,
            mandate_id=None,
            subscription_id=None,
            created_at="2024-02-01T10:00:00+00:00",
            paid_at="2024-02-01T10:05:00+00:00",
            description=None,
            metadata={},
            sequence_type=None,
        )

        def deliver():
            self.donation.reload()  # the webhook saves the donation; avoid a stale timestamp
            status = check_payment_processing_status(self.donation, self.payment_id)
            result = process_successful_payment_with_idempotency(self.donation, payment, status)
            return frappe.get_doc("Payment Entry", result["payment_entry"])

        first = self._book_then_staff_cancel(deliver)
        self.assertEqual(self._rows(docstatus=1), [])
        self._assert_one_new_live_entry(first, deliver())
        self.assertEqual(
            frappe.db.count("Payment Entry", {"reference_no": self.payment_id, "payment_type": "Receive"}),
            2,
            "expected the cancelled audit row plus exactly one new entry",
        )

    def test_webhook_lookup_race_branch_ignores_cancelled_entries(self):
        """The inner `except` lookup (duplicate-race recovery) must not hand back a cancelled
        row. The unique key is cleared on the cancelled row so the insert cannot collide on
        it; the race is simulated by forcing the duplicate branch."""
        first = self._book_then_staff_cancel(
            lambda: create_payment_entry_for_donation(self.donation, self._webhook_data())
        )
        with patch(
            "verenigingen.verenigingen_payments.mollie.api.payment_webhook.insert_and_submit_atomically",
            side_effect=frappe.DuplicateEntryError("Payment Entry", "x", Exception("dup")),
        ):
            result = create_payment_entry_for_donation(self.donation, self._webhook_data())
        self.assertFalse(
            result is not None and result.name == first.name,
            "the duplicate-race branch returned the cancelled Payment Entry",
        )

    def test_unified_receive_redelivery_after_staff_cancel_books_one_new_entry(self):
        first = self._book_then_staff_cancel(self._unified)
        self._assert_one_new_live_entry(first, self._unified())

    def test_factory_redelivery_after_staff_cancel_books_one_new_entry(self):
        from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import (
            PaymentContext,
        )
        from verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory import (
            PaymentEntryFactory,
        )

        context = PaymentContext("donation", "Donation", self.donation.name)
        data = {"payment_id": self.payment_id, "amount": "100.00"}
        factory = PaymentEntryFactory()

        def book():
            return factory.create_payment_entry(context, data, customer=self.customer)

        first = self._book_then_staff_cancel(book)
        self._assert_one_new_live_entry(first, book())
