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

A REVERSED chargeback (``reversedAt`` set, a won dispute) is covered at the bottom (#638
ruling); what an already-booked-then-failed refund should do is not (accounting policy,
not settled).

Run:
    bench --site test_site_12 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_reversal_discovery_status_date
"""

from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import flt, getdate

from verenigingen.tests.utils.clock_race import assert_written_today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_mollie_dues_reversal_booking import _DuesReversalFixture
from verenigingen.tests.payment.test_unified_idempotency_manager import (
    _FakeMollieClient,
    _FakePayment,
)
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

#: A date no Fiscal Year covers; asserted below, not assumed. No FY row is created.
OUTSIDE_EVERY_FISCAL_YEAR = "1980-06-15T12:00:00+00:00"
FY_ERROR_LOG = "Mollie Reversal Date Outside Fiscal Year"

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


def _assert_no_fiscal_year_covers_the_date(test):
    from erpnext.accounts.utils import get_fiscal_year

    test.assertFalse(
        get_fiscal_year(getdate("1980-06-15"), verbose=0, raise_on_missing=False),
        "fixture problem: a Fiscal Year covers the out-of-year date",
    )


class TestDuesReversalDiscovery(_DuesReversalFixture):
    """The dues sweep (``_book_dues_reversals``) through real discovery + booking."""

    def _dues_sweep_1806(self, refunds=(), chargebacks=()):
        payment = {"amountRefunded": {"value": "1.00", "currency": "EUR"}}
        with patch(CLIENT, return_value=_FakeMollieClient(payment=_FakePayment(refunds, chargebacks))):
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
        result = self._dues_sweep_1806(refunds=refunds)

        self.assertEqual(result["status"], "success", result)
        self.assertEqual(len(self._je("refund", paid_id)), 1, "the paid-out refund was not booked")
        for status in NOT_PAID_OUT:
            self.assertEqual(
                self._je("refund", f"re_{status}_{tag}"), [], f"a {status} refund was booked as paid out"
            )
        self.assertEqual(self._outstanding(), 10.0, "only the one paid-out refund may reopen the invoice")

    def test_a_refund_that_is_not_yet_paid_out_is_booked_once_it_settles(self):
        refund_id = f"re_settles_{frappe.generate_hash(length=6)}"
        self._dues_sweep_1806(refunds=[_refund_row_for_1806(refund_id, "pending")])
        self.assertEqual(self._je("refund", refund_id), [])
        self.assertEqual(self._outstanding(), 0.0)

        self._dues_sweep_1806(refunds=[_refund_row_for_1806(refund_id, "refunded")])
        self.assertEqual(len(self._je("refund", refund_id)), 1, "skipping must not be permanent")
        self.assertEqual(self._outstanding(), 10.0)

    def test_a_refund_without_a_status_is_not_booked(self):
        """Mollie always sends one; an unknown state must not be presumed paid out."""
        refund_id = f"re_nostatus_{frappe.generate_hash(length=6)}"
        self._dues_sweep_1806(refunds=[_refund_row_for_1806(refund_id, None)])
        self.assertEqual(self._je("refund", refund_id), [])

    def test_a_refund_is_booked_on_its_own_date_not_today(self):
        created_at, day = _noon_utc_days_ago(5)
        refund_id = f"re_dated_{frappe.generate_hash(length=6)}"
        self._dues_sweep_1806(refunds=[_refund_row_for_1806(refund_id, "refunded", created_at=created_at)])
        names = self._je("refund", refund_id)
        self.assertEqual(len(names), 1)
        self.assertEqual(getdate(frappe.db.get_value("Journal Entry", names[0], "posting_date")), day)
        self.assertNotEqual(day, getdate(), "fixture problem: the date must differ from today")

    def test_a_chargeback_is_booked_on_its_own_date_not_today(self):
        created_at, day = _noon_utc_days_ago(6)
        chargeback_id = f"chb_dated_{frappe.generate_hash(length=6)}"
        result = self._dues_sweep_1806(chargebacks=[_chargeback_row_for_1806(chargeback_id, created_at=created_at)])
        self.assertEqual(result["status"], "success", result)
        names = self._je("chargeback", chargeback_id)
        self.assertEqual(len(names), 1)
        self.assertEqual(getdate(frappe.db.get_value("Journal Entry", names[0], "posting_date")), day)
        self.assertNotEqual(day, getdate(), "fixture problem: the date must differ from today")

    def test_a_chargeback_dated_outside_every_fiscal_year_is_booked_on_today(self):
        """Booking on Mollie's own date must not make an old reversal unbookable (#1806)."""
        _assert_no_fiscal_year_covers_the_date(self)
        self.expectErrorLog(FY_ERROR_LOG)
        chargeback_id = f"chb_oldfy_{frappe.generate_hash(length=6)}"
        result = self._dues_sweep_1806(chargebacks=[_chargeback_row_for_1806(chargeback_id, created_at=OUTSIDE_EVERY_FISCAL_YEAR)])
        self.assertEqual(result["status"], "success", result)
        names = self._je("chargeback", chargeback_id)
        self.assertEqual(len(names), 1)
        assert_written_today(self, frappe.db.get_value("Journal Entry", names[0], "posting_date"))

    def test_a_refund_dated_outside_every_fiscal_year_is_booked_on_today(self):
        _assert_no_fiscal_year_covers_the_date(self)
        self.expectErrorLog(FY_ERROR_LOG)
        refund_id = f"re_oldfy_{frappe.generate_hash(length=6)}"
        result = self._dues_sweep_1806(refunds=[_refund_row_for_1806(refund_id, "refunded", created_at=OUTSIDE_EVERY_FISCAL_YEAR)])
        self.assertEqual(result["status"], "success", result)
        names = self._je("refund", refund_id)
        self.assertEqual(len(names), 1)
        assert_written_today(self, frappe.db.get_value("Journal Entry", names[0], "posting_date"))


class TestReversedChargebackDues638(_DuesReversalFixture):
    """#638 ruling: a chargeback Mollie reports as reversed is not booked; one booked earlier
    is countered, once. Through ``_book_dues_reversals``, the seam the payment webhook's DUES
    branch calls, with only the Mollie client stubbed. (The forward DUES routing is not
    driven here; the fixture books the forward Payment Entry directly.)"""

    REVERSED_AT = "2025-05-02T09:00:00+00:00"

    def _sweep_638(self, chargeback_id, reversed_at, charged_back="0.00"):
        payment = {"amountChargedBack": {"value": charged_back, "currency": "EUR"}}
        chargebacks = [
            _chargeback_row_for_1806(chargeback_id, amount=f"{self.INVOICE_AMOUNT:.2f}", reversed_at=reversed_at)
        ]
        with patch(CLIENT, return_value=_FakeMollieClient(payment=_FakePayment((), chargebacks))):
            return UnifiedWebhookWrapperService()._book_dues_reversals(
                self.payment_id, payment, {"status": "success"}
            )

    def _counters(self, chargeback_id):
        return frappe.get_all(
            "Journal Entry",
            filters={
                "cheque_no": build_reversal_key(self.payment_id, "chargeback", f"{chargeback_id}_reversed"),
                "docstatus": 1,
            },
            pluck="name",
        )

    def test_a_chargeback_reversed_at_first_sight_is_not_booked(self):
        chargeback_id = f"chb_won_{frappe.generate_hash(length=6)}"
        # amountChargedBack is still non-zero here so the sweep reaches discovery at all.
        result = self._sweep_638(chargeback_id, self.REVERSED_AT, charged_back="50.00")
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(frappe.get_all("Journal Entry", filters={"cheque_no": ["like", f"{self.payment_id}_chargeback_%"]}), [])
        self.assertEqual(self._outstanding(), 0.0)

    def test_a_booked_chargeback_that_is_later_reversed_restores_the_invoice_once(self):
        chargeback_id = f"chb_won_{frappe.generate_hash(length=6)}"
        first = self._sweep_638(chargeback_id, None, charged_back="50.00")
        self.assertEqual(first["status"], "success", first)
        self.assertEqual(len(self._journal_entries_for(chargeback_id, "chargeback")), 1)
        self.assertEqual(self._outstanding(), self.INVOICE_AMOUNT, "precondition: chargeback re-opened the invoice")

        # The dispute is won: Mollie now reports amountChargedBack 0.00 AND reversedAt.
        second = self._sweep_638(chargeback_id, self.REVERSED_AT)

        self.assertEqual(second["status"], "success", second)
        counters = self._counters(chargeback_id)
        self.assertEqual(len(counters), 1, f"expected one counter-entry, got {counters}")
        self.assertEqual(self._outstanding(), 0.0, "the counter-entry must close the invoice again")
        rows = self._gl_rows(counters[0])
        receivable = [r for r in rows if r["account"] == self.receivable]
        clearing = [r for r in rows if r["account"] == self.clearing_account]
        self.assertEqual(flt(receivable[0]["credit"]), self.INVOICE_AMOUNT, rows)
        self.assertEqual(receivable[0]["against_voucher"], self.invoice, rows)
        self.assertEqual(flt(clearing[0]["debit"]), self.INVOICE_AMOUNT, rows)
        self.assertEqual(
            frappe.db.get_value("Journal Entry", self._journal_entries_for(chargeback_id, "chargeback")[0], "docstatus"),
            1,
            "the chargeback entry must be countered, not cancelled",
        )

        third = self._sweep_638(chargeback_id, self.REVERSED_AT)

        self.assertEqual(third["status"], "success", third)
        self.assertEqual(self._counters(chargeback_id), counters, "a redelivery booked another counter-entry")
        self.assertEqual(self._outstanding(), 0.0)


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

    def _donation_sweep_1806(self, refunds):
        with patch(CLIENT, return_value=_FakeMollieClient(payment=_FakePayment(refunds))):
            state = UnifiedIdempotencyManager().check_payment_processing_state(
                self.payment_id, include_mollie_api=True
            )
        self.assertFalse(state.refund_check_failed, "fixture problem: discovery failed")
        return UnifiedWebhookWrapperService()._process_pending_refunds(
            self.donation, self.payment_id, state.pending_refunds
        )

    def _booked_artefacts_1806(self, refund_id):
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
        self._donation_sweep_1806(refunds)

        booked = self._booked_artefacts_1806(paid_id)
        self.assertEqual(len(booked), 1, "the paid-out refund was not booked")
        self.assertEqual(getdate(booked[0]["posting_date"]), day)
        self.assertNotEqual(day, getdate(), "fixture problem: the date must differ from today")
        for status in NOT_PAID_OUT:
            self.assertEqual(
                self._booked_artefacts_1806(f"re_{status}_{tag}"), [], f"a {status} refund was booked as paid out"
            )

    def test_a_donation_refund_dated_outside_every_fiscal_year_is_booked_on_today(self):
        _assert_no_fiscal_year_covers_the_date(self)
        self.expectErrorLog(FY_ERROR_LOG)
        refund_id = f"re_oldfy_{frappe.generate_hash(length=6)}"
        self._donation_sweep_1806(
            [_refund_row_for_1806(refund_id, "refunded", amount="40.00", created_at=OUTSIDE_EVERY_FISCAL_YEAR)]
        )
        booked = self._booked_artefacts_1806(refund_id)
        self.assertEqual(len(booked), 1, "the refund was not booked")
        assert_written_today(self, booked[0]["posting_date"])
