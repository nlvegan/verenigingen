"""A refund or chargeback whose webhook delivery was lost must still get booked (#2140).

Discovery ran only inside a payment-webhook delivery. ``sweep_missed_reversals``
lists the account's reversals at Mollie and books what is not booked yet through
the same discovery and the same reversal keys.

Only the Mollie HTTP client is stubbed (``MollieClient._get_mollie_client``); the
discovery, the booking and the ledger are real. The forward payment is a real
dues Sales Invoice + Payment Entry, so the booking is a real reversing Journal
Entry and the assertions read GL-backed ``outstanding_amount``.

Run:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_reversal_rediscovery_sweep_2140
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import frappe
from frappe.utils import getdate
from rq.timeouts import JobTimeoutException

from verenigingen.tests.payment.test_mollie_dues_reversal_booking import _DuesReversalFixture
from verenigingen.verenigingen_payments.mollie.services import reversal_rediscovery_sweep
from verenigingen.verenigingen_payments.mollie.services.reversal_rediscovery_sweep import (
    sweep_missed_reversals,
)
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)


class _Page(list):
    """A one-page stand-in for the SDK's PaginationList."""

    def has_next(self):
        return False


class _FakeMollie:
    """The Mollie HTTP boundary: account-level lists plus per-payment lists."""

    def __init__(self, refunds=(), chargebacks=()):
        self._refunds = list(refunds)
        self._chargebacks = list(chargebacks)
        outer = self

        class _Resource:
            def __init__(self, items):
                self._items = items

            def list(self, **_):
                return _Page(self._items)

        class _Payments:
            def get(self, payment_id):
                class _Payment:
                    def __init__(self):
                        mine = lambda items: [i for i in items if i["paymentId"] == payment_id]  # noqa: E731
                        self.refunds = type(
                            "R", (), {"list": lambda s, **_: {"_embedded": {"refunds": mine(outer._refunds)}}}
                        )()
                        self.chargebacks = type("C", (), {"list": lambda s, **_: mine(outer._chargebacks)})()

                return _Payment()

        self.refunds = _Resource(self._refunds)
        self.chargebacks = _Resource(self._chargebacks)
        self.payments = _Payments()


def _iso_days_ago(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class TestReversalRediscoverySweep(_DuesReversalFixture):
    def _refund(self, status="refunded", amount=20.0, payment_id=None, days_ago=0):
        return {
            "id": f"re_{frappe.generate_hash(length=8)}",
            "paymentId": payment_id or self.payment_id,
            "status": status,
            "amount": {"value": f"{amount:.2f}", "currency": "EUR"},
            "createdAt": _iso_days_ago(days_ago),
        }

    def _chargeback(self, amount=20.0):
        return {
            "id": f"chb_{frappe.generate_hash(length=8)}",
            "paymentId": self.payment_id,
            "amount": {"value": f"{amount:.2f}", "currency": "EUR"},
            "createdAt": _iso_days_ago(),
            "reason": {"code": "AC01", "description": "test"},
        }

    def _sweep(self, refunds=(), chargebacks=()):
        fake = _FakeMollie(refunds, chargebacks)
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_mollie_client",
            return_value=fake,
        ):
            return sweep_missed_reversals()

    def test_a_refund_the_webhook_missed_is_booked(self):
        refund = self._refund()
        summary = self._sweep([refund])
        self.assertEqual(summary["errors"], [], summary)
        self.assertEqual(summary["reversals_booked"], 1)
        self.assertEqual(len(self._journal_entries_for(refund["id"])), 1)
        self.assertEqual(self._outstanding(), 20.0)

    def test_running_it_twice_books_once(self):
        refund = self._refund()
        self._sweep([refund])
        second = self._sweep([refund])
        self.assertEqual(second["reversals_booked"], 0)
        self.assertEqual(second["payments_checked"], 0, "an already booked refund must not be re-checked")
        self.assertEqual(len(self._journal_entries_for(refund["id"])), 1)
        self.assertEqual(self._outstanding(), 20.0, "the invoice was restored twice")

    def test_a_refund_the_webhook_already_booked_is_not_booked_again(self):
        refund = self._refund()
        _, booked = self._reverse(20.0, reversal_id=refund["id"])
        self.assertEqual(booked.get("status"), "success", booked)

        summary = self._sweep([refund])
        self.assertEqual(summary["reversals_booked"], 0)
        self.assertEqual(len(self._journal_entries_for(refund["id"])), 1)
        self.assertEqual(self._outstanding(), 20.0)

    def test_a_refund_not_yet_paid_out_is_skipped(self):
        """#1806: queued/pending/processing/failed/canceled books nothing."""
        statuses = ("queued", "pending", "processing", "failed", "canceled")
        refunds = [self._refund(status=s, amount=5.0) for s in statuses]
        summary = self._sweep(refunds)
        self.assertEqual(summary["reversals_booked"], 0, summary)
        # With the manager's own filter alone this would still book nothing; the
        # sweep's pre-filter is what keeps the payment from being checked at all.
        self.assertEqual(summary["payments_checked"], 0, "a non-paid refund must not make a candidate")
        for refund in refunds:
            self.assertEqual(self._journal_entries_for(refund["id"]), [], refund["status"])
        self.assertEqual(self._outstanding(), 0.0)

    def test_only_the_paid_out_refund_of_a_mixed_payment_is_booked(self):
        paid, queued = self._refund(amount=20.0), self._refund(status="queued", amount=10.0)
        summary = self._sweep([queued, paid])
        self.assertEqual(summary["reversals_booked"], 1, summary)
        self.assertEqual(len(self._journal_entries_for(paid["id"])), 1)
        self.assertEqual(self._journal_entries_for(queued["id"]), [])
        self.assertEqual(self._outstanding(), 20.0)

    def test_a_refund_of_a_payment_we_never_booked_is_left_alone(self):
        stranger = self._refund(payment_id="tr_unknown_2140")
        summary = self._sweep([stranger])
        self.assertEqual(summary["payments_not_ours"], 1)
        self.assertEqual(summary["reversals_booked"], 0)
        self.assertEqual(summary["errors"], [], "a foreign payment is not an error")

    def test_a_chargeback_the_webhook_missed_is_booked_once(self):
        chargeback = self._chargeback()
        summary = self._sweep(chargebacks=[chargeback])
        self.assertEqual(summary["errors"], [], summary)
        self.assertEqual(summary["reversals_booked"], 1)
        self.assertEqual(len(self._journal_entries_for(chargeback["id"], "chargeback")), 1)
        self.assertEqual(self._outstanding(), 20.0)

        self._sweep(chargebacks=[chargeback])
        self.assertEqual(len(self._journal_entries_for(chargeback["id"], "chargeback")), 1)
        self.assertEqual(self._outstanding(), 20.0)

    # ---- #2140 review round 2 ----------------------------------------------

    def _second_payment(self):
        """A second, independent booked dues payment. Returns (payment_id, invoice, restore())."""
        first = (self.payment_id, self.invoice)
        self.invoice = self._make_invoice(self.INVOICE_AMOUNT)
        self.payment_id = f"tr_dues_{frappe.generate_hash(length=8)}"
        self._make_forward_payment_entry()
        second = (self.payment_id, self.invoice)
        self.payment_id, self.invoice = first
        return second

    def _outstanding_of(self, invoice):
        return frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount")

    def test_a_refund_older_than_the_lookback_is_not_booked(self):
        """It may already be settled by hand; booking it would restore the invoice twice."""
        old = self._refund(days_ago=reversal_rediscovery_sweep._LOOKBACK_DAYS + 1)
        summary = self._sweep([old])
        self.assertEqual(summary["reversals_booked"], 0, summary)
        self.assertEqual(summary["payments_checked"], 0)
        self.assertEqual(self._journal_entries_for(old["id"]), [])
        self.assertEqual(self._outstanding(), 0.0)

    def test_a_refund_inside_the_lookback_but_behind_an_old_one_is_still_found(self):
        """Control for the stop-at-first-old rule: the list is newest-first, so it only
        stops AFTER the recent items. A recent one listed first must still book."""
        recent = self._refund(days_ago=reversal_rediscovery_sweep._LOOKBACK_DAYS - 1)
        old = self._refund(days_ago=reversal_rediscovery_sweep._LOOKBACK_DAYS + 1)
        summary = self._sweep([recent, old])
        self.assertEqual(summary["reversals_booked"], 1, summary)
        self.assertEqual(len(self._journal_entries_for(recent["id"])), 1)
        self.assertEqual(self._journal_entries_for(old["id"]), [])

    def test_the_cap_is_honoured_and_the_rest_drain_on_the_next_run(self):
        second_payment, second_invoice = self._second_payment()
        refunds = [self._refund(), self._refund(payment_id=second_payment)]
        with patch.object(reversal_rediscovery_sweep, "_MAX_PAYMENTS_PER_RUN", 1):
            first = self._sweep(refunds)
            self.assertEqual(first["payments_checked"], 1, first)
            self.assertEqual(first["reversals_booked"], 1, first)
            second = self._sweep(refunds)
        self.assertEqual(second["reversals_booked"], 1, second)
        self.assertEqual(self._outstanding(), 20.0)
        self.assertEqual(flt_(self._outstanding_of(second_invoice)), 20.0)
        for refund in refunds:
            key_jes = frappe.get_all(
                "Journal Entry",
                filters={"cheque_no": f"{refund['paymentId']}_refund_{refund['id']}", "docstatus": ["!=", 2]},
            )
            self.assertEqual(len(key_jes), 1, refund)

    def test_a_job_timeout_ends_the_sweep_instead_of_being_recorded(self):
        refund = self._refund()
        with patch.object(
            UnifiedWebhookWrapperService, "book_pending_reversals", side_effect=JobTimeoutException()
        ):
            with self.assertRaises(JobTimeoutException):
                self._sweep([refund])

    def test_a_job_timeout_while_listing_at_mollie_ends_the_sweep(self):
        """The listing is one of the long Mollie HTTP calls; its handler must re-raise a timeout."""
        fake = _FakeMollie([self._refund()])

        def timing_out_list(**_):
            raise JobTimeoutException()

        fake.refunds.list = timing_out_list
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_mollie_client",
            return_value=fake,
        ):
            with self.assertRaises(JobTimeoutException):
                sweep_missed_reversals()

    def test_a_payment_mollie_404s_is_an_error_entry_not_a_silent_skip(self):
        """#1805: the webhook acks a 404, but the safety net must still record it booked nothing.

        The ids come from Mollie's own listing, so a 404 on ``payments.get`` for one is serious.
        """
        from mollie.api.error import NotFoundError

        refund = self._refund()
        fake = _FakeMollie([refund])

        def not_found(payment_id):
            raise NotFoundError({"status": 404, "title": "Not Found", "detail": "x"})

        fake.payments.get = not_found
        self.expectErrorLog("Mollie reversal rediscovery sweep: problem(s)")
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_mollie_client",
            return_value=fake,
        ):
            summary = sweep_missed_reversals()

        self.assertEqual(summary["reversals_booked"], 0, summary)
        self.assertEqual([e["payment_id"] for e in summary["errors"]], [self.payment_id], summary)
        self.assertIn("404", summary["errors"][0]["error"])
        self.assertEqual(self._journal_entries_for(refund["id"]), [])

    def test_a_payment_that_fails_midway_leaves_nothing_and_the_next_one_books(self):
        """The stub writes an uncommitted row for the first payment and then raises."""
        second_payment, second_invoice = self._second_payment()
        bad, good = self._refund(), self._refund(payment_id=second_payment)
        real = UnifiedWebhookWrapperService.book_pending_reversals
        marker = f"sweep-2140-{frappe.generate_hash(length=8)}"

        def write_then_fail(wrapper, payment_id, state):
            if payment_id == self.payment_id:
                frappe.get_doc({"doctype": "Note", "title": marker, "content": "partial"}).insert()
                raise RuntimeError("boom midway")
            return real(wrapper, payment_id, state)

        with patch.object(UnifiedWebhookWrapperService, "book_pending_reversals", write_then_fail):
            self.expectErrorLog("Mollie reversal rediscovery sweep: problem(s)")
            summary = self._sweep([bad, good])

        self.assertEqual(len(summary["errors"]), 1, summary)
        self.assertEqual(summary["errors"][0]["payment_id"], self.payment_id)
        self.assertFalse(frappe.db.exists("Note", {"title": marker}), "the failed payment's partial row survived")
        self.assertEqual(summary["reversals_booked"], 1, summary)
        self.assertEqual(flt_(self._outstanding_of(second_invoice)), 20.0)
        self.assertEqual(self._outstanding(), 0.0)


def flt_(value):
    return float(value or 0)
