"""
#2355: ``UnifiedIdempotencyManager`` must see a reversal that is ALREADY booked.

Reversals are booked as Journal Entries (``cheque_no``) or Payment Entries
(``reference_no``) under ``build_reversal_key`` = ``{payment}_{type}_{id}``. The manager
used to look for Payment Entries ``reference_no LIKE 'chb_%'`` (chargebacks) and for
Payment Entries only (refunds), so a booked JE reversal was reported pending forever
and re-fed to the booker on every check.

Real booking (``_book_dues_reversals`` / ``_process_pending_refunds``), real discovery;
only the Mollie HTTP client is the shared fake. Assertions read the manager's result.

Run:
    PYTHONPATH=<worktree> bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_unified_idempotency_sees_booked_reversals
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_mollie_dues_reversal_booking import _DuesReversalFixture
from verenigingen.tests.payment.test_mollie_reversal_discovery_status_date import (
    _chargeback_row_for_1806,
    _refund_row_for_1806,
)
from verenigingen.tests.payment.test_mollie_reversal_single_booking import (
    _ensure_mollie_named_bank_account,
)
from verenigingen.tests.payment.test_unified_idempotency_manager import (
    _FakeMollieClient,
    _FakePayment,
)
from verenigingen.tests.services.test_donation_refund_journal_entry_creator_coverage import (
    COMPANY,
    _RefundFixtureMixin,
)
from verenigingen.tests.support.mollie_settings import (
    pin_mollie_clearing_account,
    pin_verenigingen_settings,
)
from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
    UnifiedIdempotencyManager,
)
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)
from verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency import (
    build_reversal_key,
    find_booked_reversal,
)
from verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator import (
    create_refund_payment_entry,
)

CLIENT = "verenigingen.verenigingen_payments.mollie.core.client.MollieClient"


def _check(payment_id, refunds=(), chargebacks=()):
    with patch(CLIENT, return_value=_FakeMollieClient(payment=_FakePayment(refunds, chargebacks))):
        return UnifiedIdempotencyManager().check_payment_processing_state(
            payment_id, include_mollie_api=True
        )


class TestManagerSeesJournalEntryReversals(_DuesReversalFixture):
    """Dues reversals are booked as Journal Entries."""

    def _book(self, refunds=(), chargebacks=()):
        payment = {"amountRefunded": {"value": "1.00", "currency": "EUR"}}
        with patch(CLIENT, return_value=_FakeMollieClient(payment=_FakePayment(refunds, chargebacks))):
            result = UnifiedWebhookWrapperService()._book_dues_reversals(
                self.payment_id, payment, {"status": "success"}
            )
        self.assertEqual(result["status"], "success", result)

    def test_a_booked_chargeback_is_processed_not_pending(self):
        chb_id = f"chb_{frappe.generate_hash(length=8)}"
        rows = [_chargeback_row_for_1806(chb_id)]

        before = _check(self.payment_id, chargebacks=rows)
        self.assertEqual([c["chargeback_id"] for c in before.pending_chargebacks], [chb_id])

        self._book(chargebacks=rows)
        booked = find_booked_reversal(build_reversal_key(self.payment_id, "chargeback", chb_id))
        self.assertEqual(booked[0], "Journal Entry", "fixture problem: expected a JE booking")

        after = _check(self.payment_id, chargebacks=rows)
        self.assertEqual(after.pending_chargebacks, [], "a booked chargeback is still pending")
        self.assertEqual([c["chargeback_id"] for c in after.chargebacks_processed], [chb_id])
        self.assertEqual(after.chargebacks_processed[0]["payment_entry"], booked[1])

    def test_a_booked_refund_is_processed_not_pending(self):
        re_id = f"re_{frappe.generate_hash(length=8)}"
        rows = [_refund_row_for_1806(re_id, "refunded")]

        before = _check(self.payment_id, refunds=rows)
        self.assertEqual([r["refund_id"] for r in before.pending_refunds], [re_id])

        self._book(refunds=rows)
        after = _check(self.payment_id, refunds=rows)
        self.assertEqual(after.pending_refunds, [], "a booked refund is still pending")
        self.assertEqual(after.refunds_processed, [re_id])

    def test_only_the_booked_reversal_leaves_pending(self):
        """Control: an unbooked sibling of a booked reversal must stay pending."""
        tag = frappe.generate_hash(length=6)
        booked_chb, open_chb = f"chb_a_{tag}", f"chb_b_{tag}"
        booked_re, open_re = f"re_a_{tag}", f"re_b_{tag}"
        self._book(
            refunds=[_refund_row_for_1806(booked_re, "refunded")],
            chargebacks=[_chargeback_row_for_1806(booked_chb)],
        )
        state = _check(
            self.payment_id,
            refunds=[_refund_row_for_1806(r, "refunded") for r in (booked_re, open_re)],
            chargebacks=[_chargeback_row_for_1806(c) for c in (booked_chb, open_chb)],
        )
        self.assertEqual([r["refund_id"] for r in state.pending_refunds], [open_re])
        self.assertEqual([c["chargeback_id"] for c in state.pending_chargebacks], [open_chb])

    def test_a_cancelled_booking_frees_the_reversal(self):
        """Same predicate as the booker (docstatus != 2): a cancelled JE is not a booking."""
        chb_id = f"chb_{frappe.generate_hash(length=8)}"
        rows = [_chargeback_row_for_1806(chb_id)]
        self._book(chargebacks=rows)
        _, je = find_booked_reversal(build_reversal_key(self.payment_id, "chargeback", chb_id))
        frappe.get_doc("Journal Entry", je).cancel()

        state = _check(self.payment_id, chargebacks=rows)
        self.assertEqual([c["chargeback_id"] for c in state.pending_chargebacks], [chb_id])
        self.assertEqual(state.chargebacks_processed, [])


class TestManagerSeesDonationReversals(_RefundFixtureMixin, EnhancedTestCase):
    """Donation refunds: Journal Entry (sweep route) vs Payment Entry (refund webhook)."""

    def setUp(self):
        super().setUp()
        self.ensure_mode_of_payment("Mollie", "Bank")
        self.ensure_mode_of_payment("Mollie Refund", "Bank")
        self.clearing_account = self._ensure_clearing_account()
        self.income_account = self._ensure_income_account()
        self.bank_account = self._ensure_bank_account(self.clearing_account)
        self.mollie_account = _ensure_mollie_named_bank_account()
        self.receivable = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
        )
        pin_verenigingen_settings(self, company=COMPANY, donation_receivable_account=self.receivable)
        pin_mollie_clearing_account(self, self.clearing_account)

        self.donor = self._make_donor()
        frappe.get_doc("Donor", self.donor).get_or_create_customer()
        self.payment_id = f"tr_idem_{frappe.generate_hash(length=8)}"
        self.refund_id = f"re_idem_{frappe.generate_hash(length=8)}"
        self.donation = self._make_donation(self.donor, 100.0)
        frappe.db.set_value("Donation", self.donation.name, "payment_id", self.payment_id)
        self.donation.payment_id = self.payment_id
        self.key = build_reversal_key(self.payment_id, "refund", self.refund_id)
        self.rows = [_refund_row_for_1806(self.refund_id, "refunded", amount="100.00")]

    def _book_journal_entry(self):
        """The sweep route's artefact: Bank Transaction + Journal Entry."""
        bt = self._make_withdrawal_bank_transaction(100.0, self.key, self.bank_account)
        je = self._build_creator().create_refund_journal_entry(
            refund_id=self.refund_id,
            refund_amount=100.0,
            refund_date=today(),
            donation_doc=self.donation,
            original_payment_id=self.payment_id,
            bank_transaction_name=bt,
        )
        self.assertTrue(je, "fixture problem: Journal Entry not booked")
        self.assertEqual(find_booked_reversal(self.key), ("Journal Entry", je))
        return je

    def _history_rows(self):
        return frappe.db.count(
            "Donation Payment", {"parent": self.donation.name, "mollie_payment_id": self.refund_id}
        )

    def test_a_journal_entry_refund_without_its_history_row_stays_pending_for_the_repair(self):
        """``payment_history_missing`` carries a Payment Entry name, so it cannot repair a
        Journal Entry's missing row; the booker's already-booked branch can. The manager
        must keep such a refund pending (and, run through the booker, the row appears)."""
        je = self._book_journal_entry()
        self.assertEqual(self._history_rows(), 0, "fixture problem: a history row already exists")

        state = _check(self.payment_id, refunds=self.rows)
        self.assertEqual([r["refund_id"] for r in state.pending_refunds], [self.refund_id])
        self.assertEqual(state.refunds_processed, [])
        self.assertEqual(state.payment_history_missing, [])

        UnifiedWebhookWrapperService()._process_pending_refunds(
            self.donation, self.payment_id, state.pending_refunds
        )
        self.assertEqual(self._history_rows(), 1, "the repair did not write the Journal Entry's row")
        self.assertEqual(find_booked_reversal(self.key), ("Journal Entry", je), "repair double-booked")

    def test_a_journal_entry_refund_with_its_history_row_is_processed(self):
        self._book_journal_entry()
        state = _check(self.payment_id, refunds=self.rows)
        UnifiedWebhookWrapperService()._process_pending_refunds(
            self.donation, self.payment_id, state.pending_refunds
        )
        self.assertEqual(self._history_rows(), 1, "fixture problem: no history row")

        after = _check(self.payment_id, refunds=self.rows)
        self.assertEqual(after.pending_refunds, [], "a fully booked JE refund is still pending")
        self.assertEqual(after.refunds_processed, [self.refund_id])

    def test_a_payment_entry_refund_without_history_row_is_still_history_missing(self):
        """Unchanged behaviour: a Payment Entry booking keeps its payment_history_missing route."""
        pe = create_refund_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            refund_id=self.refund_id,
            refund_amount=100.0,
            refund_date=today(),
        )
        self.assertIsNotNone(pe, "fixture problem: refund Payment Entry not booked")
        state = _check(self.payment_id, refunds=self.rows)
        self.assertEqual(state.pending_refunds, [])
        self.assertEqual([m["payment_entry"] for m in state.payment_history_missing], [pe.name])
