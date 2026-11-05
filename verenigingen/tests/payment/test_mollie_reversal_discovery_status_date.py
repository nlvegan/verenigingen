"""
#1806: Mollie reversal DISCOVERY must read a refund's status and carry the
reversal's own date, through the real discovery and the real booking.

What Mollie documents (https://docs.mollie.com/reference/get-refund): a refund's
``status`` is one of ``queued``, ``pending``, ``processing``, ``refunded``,
``failed``, ``canceled``. Only ``refunded`` means the money reached the payer.
A chargeback carries ``createdAt`` (and ``reversedAt``, null until reversed).
The Mollie TEST account on this bench returned 96 refunds, all ``refunded``, and
0 chargebacks, so the other statuses are from the documentation, not observed.

Only the Mollie HTTP client is stubbed. Discovery
(``UnifiedIdempotencyManager.check_payment_processing_state``) and booking
(``_book_dues_reversals`` / ``_process_pending_refunds``) are the real code, and
assertions are on the Journal Entry / Payment Entry rows they leave behind.

Not covered on purpose (accounting policy, not settled): what a REVERSED chargeback
(``reversedAt`` set) or an already-booked-then-failed refund should do.

Run:
    bench --site test_site_12 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_reversal_discovery_status_date
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import flt, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_mollie_dues_reversal_booking import _DuesReversalFixture
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
from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
    UnifiedIdempotencyManager,
)
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)
from verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency import build_reversal_key
from verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator import (
    create_unified_payment_entry,
)

NOT_PAID_OUT = ("queued", "pending", "processing", "failed", "canceled")
CLIENT = "verenigingen.verenigingen_payments.mollie.core.client.MollieClient"


def _noon_utc_days_ago(days_ago):
    """Noon UTC on a past day, as Mollie writes ``createdAt``; returns (iso, date)."""
    day = getdate() - timedelta(days=days_ago)
    return f"{day.isoformat()}T12:00:00+00:00", day


def _refund_row_for_1806(refund_id, status, amount="10.00", created_at=None):
    row = {
        "id": refund_id,
        "amount": {"value": amount, "currency": "EUR"},
        "createdAt": created_at or _noon_utc_days_ago(2)[0],
    }
    if status is not None:
        row["status"] = status
    return row


def _chargeback_row_for_1806(chargeback_id, amount="10.00", created_at=None, reversed_at=None):
    return {
        "id": chargeback_id,
        "amount": {"value": amount, "currency": "EUR"},
        "createdAt": created_at or _noon_utc_days_ago(2)[0],
        "reversedAt": reversed_at,
        "reason": {"code": "AC01"},
    }


class _FakeMollieClient:
    """Stands in for ``MollieClient()._get_mollie_client()`` -- the HTTP boundary only."""

    def __init__(self, refunds=(), chargebacks=()):
        self.refunds, self.chargebacks = list(refunds), list(chargebacks)
        self.payments = SimpleNamespace(get=self._get)

    def _get_mollie_client(self):
        return self

    def _get(self, _payment_id):
        return SimpleNamespace(
            refunds=SimpleNamespace(list=lambda: {"_embedded": {"refunds": self.refunds}}),
            chargebacks=SimpleNamespace(list=lambda: self.chargebacks),
        )


class TestDuesReversalDiscovery(_DuesReversalFixture):
    """The dues sweep (``_book_dues_reversals``) through real discovery + booking."""

    def _sweep(self, refunds=(), chargebacks=()):
        payment = {"amountRefunded": {"value": "1.00", "currency": "EUR"}}
        with patch(CLIENT, return_value=_FakeMollieClient(refunds, chargebacks)):
            return UnifiedWebhookWrapperService()._book_dues_reversals(
                self.payment_id, payment, {"status": "success"}
            )

    def _je(self, reversal_type, reversal_id):
        key = build_reversal_key(self.payment_id, reversal_type, reversal_id)
        return frappe.get_all("Journal Entry", filters={"cheque_no": key, "docstatus": ["!=", 2]}, pluck="name")

    def test_only_a_refunded_refund_is_booked(self):
        tag = frappe.generate_hash(length=6)
        paid_id = f"re_paid_{tag}"
        refunds = [_refund_row_for_1806(paid_id, "refunded")] + [
            _refund_row_for_1806(f"re_{status}_{tag}", status) for status in NOT_PAID_OUT
        ]
        result = self._sweep(refunds=refunds)

        self.assertEqual(result["status"], "success", result)
        self.assertEqual(len(self._je("refund", paid_id)), 1, "the paid-out refund was not booked")
        for status in NOT_PAID_OUT:
            self.assertEqual(
                self._je("refund", f"re_{status}_{tag}"), [], f"a {status} refund was booked as paid out"
            )
        self.assertEqual(self._outstanding(), 10.0, "only the one paid-out refund may reopen the invoice")

    def test_a_refund_that_is_not_yet_paid_out_is_booked_once_it_settles(self):
        refund_id = f"re_settles_{frappe.generate_hash(length=6)}"
        self._sweep(refunds=[_refund_row_for_1806(refund_id, "pending")])
        self.assertEqual(self._je("refund", refund_id), [])
        self.assertEqual(self._outstanding(), 0.0)

        self._sweep(refunds=[_refund_row_for_1806(refund_id, "refunded")])
        self.assertEqual(len(self._je("refund", refund_id)), 1, "skipping must not be permanent")
        self.assertEqual(self._outstanding(), 10.0)

    def test_a_refund_without_a_status_is_not_booked(self):
        """Mollie always sends one; an unknown state must not be presumed paid out."""
        refund_id = f"re_nostatus_{frappe.generate_hash(length=6)}"
        self._sweep(refunds=[_refund_row_for_1806(refund_id, None)])
        self.assertEqual(self._je("refund", refund_id), [])

    def test_a_refund_is_booked_on_its_own_date_not_today(self):
        created_at, day = _noon_utc_days_ago(5)
        refund_id = f"re_dated_{frappe.generate_hash(length=6)}"
        self._sweep(refunds=[_refund_row_for_1806(refund_id, "refunded", created_at=created_at)])
        names = self._je("refund", refund_id)
        self.assertEqual(len(names), 1)
        self.assertEqual(getdate(frappe.db.get_value("Journal Entry", names[0], "posting_date")), day)
        self.assertNotEqual(day, getdate(), "fixture problem: the date must differ from today")

    def test_a_chargeback_is_booked_on_its_own_date_not_today(self):
        created_at, day = _noon_utc_days_ago(6)
        chargeback_id = f"chb_dated_{frappe.generate_hash(length=6)}"
        result = self._sweep(chargebacks=[_chargeback_row_for_1806(chargeback_id, created_at=created_at)])
        self.assertEqual(result["status"], "success", result)
        names = self._je("chargeback", chargeback_id)
        self.assertEqual(len(names), 1)
        self.assertEqual(getdate(frappe.db.get_value("Journal Entry", names[0], "posting_date")), day)
        self.assertNotEqual(day, getdate(), "fixture problem: the date must differ from today")


class TestDonationReversalDiscovery(_RefundFixtureMixin, EnhancedTestCase):
    """The donation sweep: the same discovery, then ``_process_pending_refunds``."""

    def setUp(self):
        super().setUp()
        self.ensure_mode_of_payment("Mollie", "Bank")
        self.ensure_mode_of_payment("Mollie Refund", "Bank")
        self.clearing_account = self._ensure_clearing_account()
        self._ensure_income_account()
        self._ensure_bank_account(self.clearing_account)
        _ensure_mollie_named_bank_account()
        self.receivable = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
        )
        pin_verenigingen_settings(self, company=COMPANY, donation_receivable_account=self.receivable)
        pin_mollie_clearing_account(self, self.clearing_account)

        self.donor = self._make_donor()
        frappe.get_doc("Donor", self.donor).get_or_create_customer()
        self.payment_id = f"tr_don_{frappe.generate_hash(length=8)}"
        self.donation = self._make_donation(self.donor, 100.0)
        frappe.db.set_value("Donation", self.donation.name, "payment_id", self.payment_id)
        self.donation.payment_id = self.payment_id
        forward = create_unified_payment_entry(
            donation_doc=self.donation,
            mollie_payment_id=self.payment_id,
            amount=100.0,
            payment_type="Receive",
        )
        self.assertIsNotNone(forward, "forward Payment Entry not booked - fixture problem")

    def _sweep(self, refunds):
        with patch(CLIENT, return_value=_FakeMollieClient(refunds)):
            state = UnifiedIdempotencyManager().check_payment_processing_state(
                self.payment_id, include_mollie_api=True
            )
        self.assertFalse(state.refund_check_failed, "fixture problem: discovery failed")
        return UnifiedWebhookWrapperService()._process_pending_refunds(
            self.donation, self.payment_id, state.pending_refunds
        )

    def _booked(self, refund_id):
        key = f"{self.payment_id}_refund_{refund_id}"
        return frappe.get_all(
            "Payment Entry", filters={"reference_no": key, "docstatus": ["!=", 2]}, fields=["name", "posting_date"]
        ) + frappe.get_all(
            "Journal Entry", filters={"cheque_no": key, "docstatus": ["!=", 2]}, fields=["name", "posting_date"]
        )

    def test_only_a_refunded_refund_is_booked_and_on_its_own_date(self):
        tag = frappe.generate_hash(length=6)
        created_at, day = _noon_utc_days_ago(4)
        paid_id = f"re_paid_{tag}"
        refunds = [_refund_row_for_1806(paid_id, "refunded", amount="40.00", created_at=created_at)] + [
            _refund_row_for_1806(f"re_{status}_{tag}", status, amount="40.00") for status in NOT_PAID_OUT
        ]
        self._sweep(refunds)

        booked = self._booked(paid_id)
        self.assertEqual(len(booked), 1, "the paid-out refund was not booked")
        self.assertEqual(getdate(booked[0]["posting_date"]), day)
        self.assertNotEqual(day, getdate(), "fixture problem: the date must differ from today")
        for status in NOT_PAID_OUT:
            self.assertEqual(
                self._booked(f"re_{status}_{tag}"), [], f"a {status} refund was booked as paid out"
            )
