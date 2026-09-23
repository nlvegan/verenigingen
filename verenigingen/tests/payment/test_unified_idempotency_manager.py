"""
Tests for UnifiedIdempotencyManager and PaymentIdempotencyCheckResult.

Strategy
--------
* PaymentIdempotencyCheckResult is pure logic -> assert its state-machine helpers.
* UnifiedIdempotencyManager DB-querying methods are exercised against a real
  (empty) database for the "nothing found" paths, which are the dominant code
  paths and require no heavyweight ERPNext accounting setup.
* The Mollie-SSOT refund/chargeback branches are exercised by injecting a fake
  Mollie client (the production code reaches it via
  ``MollieClient()._get_mollie_client()`` -> ``payments.get(...)``). We patch
  the ``MollieClient`` class used inside the manager so no live call is made;
  this is a true external-boundary stub, not business-logic mocking.

Target: verenigingen/verenigingen_payments/mollie/services/unified_idempotency_manager.py
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.test_donation_refund_journal_entry_creator_coverage import (
    COMPANY,
    _RefundFixtureMixin,
)
from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
    PaymentIdempotencyCheckResult,
    UnifiedIdempotencyManager,
    get_unified_idempotency_manager,
)


class _FakeRefunds:
    def __init__(self, refunds):
        self._refunds = refunds

    def list(self):
        return {"_embedded": {"refunds": self._refunds}}


class _FakeChargebacks:
    def __init__(self, chargebacks):
        self._chargebacks = chargebacks

    def list(self):
        return self._chargebacks


class _FakePayment:
    def __init__(self, refunds=None, chargebacks=None):
        self.refunds = _FakeRefunds(refunds or [])
        self.chargebacks = _FakeChargebacks(chargebacks or [])


class _FakeMollieClient:
    """Stub matching MollieClient()._get_mollie_client().payments.get(...)."""

    def __init__(self, payment=None, raise_on_get=False):
        self._payment = payment or _FakePayment()
        self._raise = raise_on_get
        self.payments = SimpleNamespace(get=self._get)

    def _get_mollie_client(self):
        return self

    def _get(self, payment_id):
        if self._raise:
            raise RuntimeError("Mollie API down")
        return self._payment


class TestPaymentIdempotencyCheckResult(FrappeTestCase):
    """Pure-logic state machine on the result object."""

    def test_fresh_result_needs_processing(self):
        r = PaymentIdempotencyCheckResult("tr_1")
        self.assertFalse(r.is_fully_processed())
        self.assertTrue(r.needs_payment_processing())
        self.assertFalse(r.has_pending_refunds())
        self.assertFalse(r.has_pending_chargebacks())

    def test_fully_processed_requires_all_three_flags(self):
        r = PaymentIdempotencyCheckResult("tr_1")
        r.payment_entry_exists = True
        r.payment_history_updated = True
        # donation_status_updated still False -> not fully processed
        self.assertFalse(r.is_fully_processed())
        r.donation_status_updated = True
        self.assertTrue(r.is_fully_processed())
        self.assertFalse(r.needs_payment_processing())

    def test_pending_refunds_and_chargebacks(self):
        r = PaymentIdempotencyCheckResult("tr_1")
        r.pending_refunds = [{"refund_id": "re_1"}]
        r.pending_chargebacks = [{"chargeback_id": "chb_1"}]
        self.assertTrue(r.has_pending_refunds())
        self.assertTrue(r.has_pending_chargebacks())


class TestUnifiedIdempotencyManagerDB(FrappeTestCase):
    """DB-backed checks against an empty database (no-match paths)."""

    def setUp(self):
        self.mgr = UnifiedIdempotencyManager()
        self.payment_id = "tr_idem_nomatch_xyz"

    def tearDown(self):
        frappe.db.rollback()

    def test_payment_entry_exists_returns_none_when_absent(self):
        self.assertIsNone(self.mgr.payment_entry_exists("tr_does_not_exist_zzz"))

    def test_check_refund_idempotency_returns_none_when_absent(self):
        self.assertIsNone(self.mgr.check_refund_idempotency("re_does_not_exist_zzz"))

    def test_state_no_payment_no_donation(self):
        """With nothing in the DB the payment needs full processing."""
        result = self.mgr.check_payment_processing_state(self.payment_id, include_mollie_api=False)
        self.assertFalse(result.payment_entry_exists)
        self.assertIsNone(result.payment_entry_name)
        self.assertFalse(result.payment_history_updated)
        self.assertFalse(result.donation_status_updated)
        self.assertTrue(result.needs_payment_processing())
        self.assertFalse(result.all_processing_complete)
        # Refund/chargeback checks skipped without API -> not flagged failed
        self.assertFalse(result.refund_check_failed)

    def test_state_links_donation_by_payment_id(self):
        """A Donation carrying this payment_id is discovered by _check_donation_state."""
        donation_name = self._make_unpaid_donation(self.payment_id)
        result = self.mgr.check_payment_processing_state(self.payment_id, include_mollie_api=False)
        self.assertEqual(result.donation_name, donation_name)
        # No submitted PE -> donation_status_updated keys off payment_entry_exists
        self.assertFalse(result.donation_status_updated)
        self.assertFalse(result.payment_history_updated)

    # ----------------------------------------------------- Mollie SSOT branches
    def test_refund_check_failed_when_mollie_raises(self):
        client = _FakeMollieClient(raise_on_get=True)
        result = PaymentIdempotencyCheckResult(self.payment_id)
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient",
            return_value=client,
        ):
            self.mgr._check_refund_processing_state(self.payment_id, result, include_mollie_api=True)
        self.assertTrue(result.refund_check_failed)
        self.assertEqual(result.pending_refunds, [])

    def test_refund_skipped_without_api(self):
        result = PaymentIdempotencyCheckResult(self.payment_id)
        self.mgr._check_refund_processing_state(self.payment_id, result, include_mollie_api=False)
        self.assertFalse(result.refund_check_failed)
        self.assertEqual(result.pending_refunds, [])

    def test_pending_refund_detected_from_mollie(self):
        """A Mollie refund with no matching Payment Entry becomes a pending refund."""
        payment = _FakePayment(
            refunds=[{"id": "re_pending1", "amount": {"value": "10.00"}, "createdAt": "2026-01-01"}]
        )
        client = _FakeMollieClient(payment=payment)
        result = PaymentIdempotencyCheckResult(self.payment_id)
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient",
            return_value=client,
        ):
            self.mgr._check_refund_processing_state(self.payment_id, result, include_mollie_api=True)
        self.assertEqual(len(result.pending_refunds), 1)
        self.assertEqual(result.pending_refunds[0]["refund_id"], "re_pending1")
        self.assertEqual(result.pending_refunds[0]["amount"], 10.0)
        self.assertFalse(result.refund_check_failed)
        self.assertEqual(result.refunds_processed, [])

    def test_no_refunds_in_mollie_leaves_state_clean(self):
        client = _FakeMollieClient(payment=_FakePayment(refunds=[]))
        result = PaymentIdempotencyCheckResult(self.payment_id)
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient",
            return_value=client,
        ):
            self.mgr._check_refund_processing_state(self.payment_id, result, include_mollie_api=True)
        self.assertFalse(result.refund_check_failed)
        self.assertEqual(result.pending_refunds, [])

    def test_chargeback_check_failed_when_mollie_raises(self):
        client = _FakeMollieClient(raise_on_get=True)
        result = PaymentIdempotencyCheckResult(self.payment_id)
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient",
            return_value=client,
        ):
            self.mgr._check_chargeback_processing_state(
                self.payment_id, result, include_mollie_api=True
            )
        self.assertTrue(result.chargeback_check_failed)

    def test_pending_chargeback_detected_from_mollie(self):
        payment = _FakePayment(
            chargebacks=[{"id": "chb_pending1", "amount": {"value": "20.00"}, "reason": {"code": "AC01"}}]
        )
        client = _FakeMollieClient(payment=payment)
        result = PaymentIdempotencyCheckResult(self.payment_id)
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient",
            return_value=client,
        ):
            self.mgr._check_chargeback_processing_state(
                self.payment_id, result, include_mollie_api=True
            )
        self.assertFalse(result.chargeback_check_failed)
        self.assertEqual(len(result.pending_chargebacks), 1)
        self.assertEqual(result.pending_chargebacks[0]["chargeback_id"], "chb_pending1")
        self.assertEqual(result.pending_chargebacks[0]["amount"], 20.0)

    def test_chargeback_object_format_supported(self):
        """safe_extract_chargeback_data handles SDK object (not just dict)."""
        chb_obj = SimpleNamespace(
            id="chb_obj1", amount=SimpleNamespace(value="5.00"), reason={"code": "AC04"}
        )
        client = _FakeMollieClient(payment=_FakePayment(chargebacks=[chb_obj]))
        result = PaymentIdempotencyCheckResult(self.payment_id)
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient",
            return_value=client,
        ):
            self.mgr._check_chargeback_processing_state(
                self.payment_id, result, include_mollie_api=True
            )
        self.assertEqual(len(result.pending_chargebacks), 1)
        self.assertEqual(result.pending_chargebacks[0]["chargeback_id"], "chb_obj1")
        self.assertEqual(result.pending_chargebacks[0]["amount"], 5.0)

    # ------------------------------------------------------------- mark_* no-ops
    def test_mark_refund_processed_does_not_raise(self):
        # Currently a logging no-op; assert it is callable and side-effect-free.
        self.assertIsNone(self.mgr.mark_refund_processed("tr_1", "re_1", "PE-1"))

    def test_mark_chargeback_processed_does_not_raise(self):
        self.assertIsNone(self.mgr.mark_chargeback_processed("tr_1", "chb_1", "PE-1"))

    def test_singleton_factory(self):
        a = get_unified_idempotency_manager()
        b = get_unified_idempotency_manager()
        self.assertIs(a, b)

    # ----------------------------------------------------------------- helpers
    def _make_unpaid_donation(self, payment_id):
        """Create a minimal unsubmitted Donation carrying ``payment_id``."""
        donor = self._make_donor()
        donation = frappe.new_doc("Donation")
        donation.donor = donor
        donation.amount = 10
        donation.donation_date = frappe.utils.nowdate()
        donation.mode_of_payment = self._any_mode_of_payment()
        donation.payment_id = payment_id
        donation.flags.ignore_mandatory = True
        donation.insert(ignore_permissions=True)
        return donation.name

    def _make_donor(self):
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Idem Test Donor"
        donor.donor_type = "Individual"
        donor.donor_email = "idem-test-donor@example.com"
        donor.flags.ignore_mandatory = True
        donor.insert(ignore_permissions=True)
        return donor.name

    def _any_mode_of_payment(self):
        return frappe.db.get_value("Mode of Payment", {}, "name") or "Cash"


class TestUnifiedIdempotencyManagerWildcardEscaping(_RefundFixtureMixin, EnhancedTestCase):
    """#1277: LIKE patterns built from unescaped Mollie payment/refund ids.

    A Mollie id routinely contains a literal ``_`` (e.g. ``"tr_abc123"``), which is
    a single-character LIKE wildcard when not escaped. Each test here books a
    Payment Entry / Sales Invoice for an UNRELATED payment/refund whose
    reference_no/remarks is NOT a literal substring of the id under test -- it
    differs at exactly the position of that id's ``_`` -- but DOES match once the
    ``_`` is read as a wildcard. That is the same class #1153 and #1258 already
    fixed at four other call sites in this codebase.
    """

    def setUp(self):
        super().setUp()
        self.clearing_account = self._ensure_clearing_account()
        self.income_account = self._ensure_income_account()
        self.receivable = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
        )
        self.mgr = UnifiedIdempotencyManager()
        donor = self._make_donor()
        self.customer = frappe.get_doc("Donor", donor).get_or_create_customer()
        if not frappe.db.exists("Mode of Payment", "Mollie Refund"):
            mop = frappe.new_doc("Mode of Payment")
            mop.mode_of_payment = "Mollie Refund"
            mop.insert(ignore_permissions=True)

    def _make_refund_payment_entry(self, reference_no, amount=10.0):
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Pay"
        pe.posting_date = frappe.utils.today()
        pe.company = COMPANY
        pe.party_type = "Customer"
        pe.party = self.customer
        pe.paid_amount = amount
        pe.received_amount = amount
        pe.reference_no = reference_no
        pe.reference_date = frappe.utils.today()
        pe.paid_from = self.clearing_account
        pe.paid_to = self.receivable
        pe.mode_of_payment = "Mollie Refund"
        pe.insert(ignore_permissions=True)
        pe.submit()
        self.track_test_record("Payment Entry", pe.name)
        return pe.name

    def _make_return_invoice(self, customer, remarks):
        invoice = self.create_test_sales_invoice(customer=customer, grand_total=1.0)
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {"return_against": invoice.name, "remarks": remarks},
            update_modified=False,
        )
        return invoice.name

    # ---------------------------------------------------- site 1: refund PE lookup
    def test_wildcard_payment_id_does_not_falsely_mark_refund_processed(self):
        """#1277 site 1: ``_check_refund_processing_state``'s ``reference_no`` LIKE
        (``f"%{payment_id}_refund_%"``). An unrelated Payment Entry booked for a
        DIFFERENT payment (the same refund_id, so a false match is observable)
        wildcard-matches payment_id_b and makes the manager believe payment_id_b's
        refund already has a Payment Entry -- silently dropping it from
        ``pending_refunds``."""
        uid = frappe.generate_hash(length=6)
        payment_id_b = f"tr_{uid}"  # realistic Mollie id shape: literal '_' after "tr"
        payment_id_a = f"trX{uid}"  # same length, '_' swapped for 'X'
        self.assertNotIn(payment_id_b, payment_id_a)  # sanity: not a literal substring

        refund_id = f"re_{uid}"
        self._make_refund_payment_entry(f"{payment_id_a}_refund_{refund_id}")

        payment = _FakePayment(
            refunds=[{"id": refund_id, "amount": {"value": "10.00"}, "createdAt": "2026-01-01"}]
        )
        client = _FakeMollieClient(payment=payment)
        result = PaymentIdempotencyCheckResult(payment_id_b)
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient",
            return_value=client,
        ):
            self.mgr._check_refund_processing_state(payment_id_b, result, include_mollie_api=True)

        self.assertEqual(
            [r["refund_id"] for r in result.pending_refunds],
            [refund_id],
            f"refund {refund_id} has no Payment Entry for payment {payment_id_b!r} -- an unrelated PE "
            f"for {payment_id_a!r} (not a literal substring) wildcard-matched instead, so it was "
            "wrongly reported as already processed",
        )

    # -------------------------------------------------- site 2: chargeback lookup
    def test_wildcard_payment_id_does_not_falsely_match_chargeback_remarks(self):
        """#1277 site 2: ``_check_chargeback_processing_state``'s ``remarks`` LIKE
        (``f"%{payment_id}%"``). An unrelated chargeback Payment Entry's remarks
        merely containing a string one character away from payment_id_b must not
        be attached to payment_id_b's chargeback state."""
        uid = frappe.generate_hash(length=6)
        payment_id_b = f"tr_{uid}"
        payment_id_a = f"trX{uid}"
        self.assertNotIn(payment_id_b, payment_id_a)

        pe_name = self._make_refund_payment_entry(reference_no=f"chb_{uid}", amount=5.0)
        frappe.db.set_value(
            "Payment Entry",
            pe_name,
            "remarks",
            f"Chargeback correction for {payment_id_a}",
            update_modified=False,
        )

        result = PaymentIdempotencyCheckResult(payment_id_b)
        self.mgr._check_chargeback_processing_state(payment_id_b, result, include_mollie_api=False)

        self.assertEqual(
            result.chargebacks_processed,
            [],
            f"remarks containing {payment_id_a!r} is not a literal substring of {payment_id_b!r} but "
            f"was wildcard-matched, wrongly attaching Payment Entry {pe_name} (a different payment) "
            "to it",
        )

    # ------------------------------------------ site 3: check_refund_idempotency
    def test_wildcard_refund_id_does_not_falsely_match_credit_note_remarks(self):
        """#1277 site 3: ``check_refund_idempotency``'s ``remarks`` LIKE
        (``f"%{refund_id}%"``) against Sales Invoice.

        Not established to be reachable from any current caller (a repo-wide grep
        for ``check_refund_idempotency`` finds only this method's own definition
        and its existing "returns None when absent" test); fixed anyway since the
        method's own docstring calls it "the ONLY method for refund idempotency
        checks" and the fix is a zero-risk one-line escape shared with the other
        sites in this class."""
        uid = frappe.generate_hash(length=6)
        refund_id_b = f"re_{uid}"
        refund_id_a = f"reX{uid}"
        self.assertNotIn(refund_id_b, refund_id_a)

        invoice_name = self._make_return_invoice(self.customer, remarks=f"Manual correction for {refund_id_a}")

        matched = self.mgr.check_refund_idempotency(refund_id_b)
        self.assertIsNone(
            matched,
            f"remarks containing {refund_id_a!r} is not a literal substring of {refund_id_b!r} but was "
            f"wildcard-matched to credit note {invoice_name}, wrongly reported as already processed",
        )


if __name__ == "__main__":
    unittest.main()
