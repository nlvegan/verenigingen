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

from unittest.mock import patch

import frappe
from frappe.utils import getdate

from verenigingen.tests.payment.test_mollie_dues_reversal_booking import _DuesReversalFixture
from verenigingen.verenigingen_payments.mollie.services.reversal_rediscovery_sweep import (
    sweep_missed_reversals,
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


class TestReversalRediscoverySweep(_DuesReversalFixture):
    def _refund(self, status="refunded", amount=20.0, payment_id=None):
        return {
            "id": f"re_{frappe.generate_hash(length=8)}",
            "paymentId": payment_id or self.payment_id,
            "status": status,
            "amount": {"value": f"{amount:.2f}", "currency": "EUR"},
            "createdAt": f"{getdate()}T10:00:00+00:00",
        }

    def _chargeback(self, amount=20.0):
        return {
            "id": f"chb_{frappe.generate_hash(length=8)}",
            "paymentId": self.payment_id,
            "amount": {"value": f"{amount:.2f}", "currency": "EUR"},
            "createdAt": f"{getdate()}T10:00:00+00:00",
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
