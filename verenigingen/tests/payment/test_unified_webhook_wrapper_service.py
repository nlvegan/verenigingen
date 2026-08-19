"""
Tests for UnifiedWebhookWrapperService.

Target:
    verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py

Strategy
--------
The service's __init__ wires up a logger + the idempotency manager singleton.
We bypass it with ``object.__new__`` and attach a real MollieLogger plus a
test-double idempotency manager, so each method can be exercised in isolation
without live Mollie calls. The Mollie API boundary inside _fetch_payment_from_mollie
is stubbed via Mollie Settings.get_mollie_client (the documented seam).

Reversal processing (process_reversal_webhook) covers the bulk of the missed
lines: input validation, idempotency, and the success path. For the success
path we stub create_unified_payment_entry at its module boundary (it is the
PaymentEntry-creation collaborator, not business logic of the wrapper) and use a
real Donation document so payment-history append is exercised against the DB.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.mollie.services import (
    webhook_wrapper_service_unified as wws,
)
from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
    PaymentIdempotencyCheckResult,
)


def _booked(forward=("donation", "Payment Entry", "PE-FORWARD-001"), reversal=None):
    """Patch what the reversal path asks about existing bookings.

    `process_reversal_webhook` no longer asks the idempotency manager whether a
    Payment Entry exists -- that question answered "no" for every donation, since
    donations book a Journal Entry (#370). It reads what was actually booked.

    These used to be driven by patching `frappe.db.get_value` wholesale. That is
    no longer workable: the path now makes **two** differently-keyed lookups (the
    forward booking, keyed on the payment id; the reversal, keyed on the compound
    reference), and a single blanket return value answers both with the same
    nonsense. Patching the two named functions says exactly which question is
    being answered, and leaves the real `get_value` alone for donation.save().

    `forward` is what `find_booked_payment` returns; `reversal` is what
    `find_booked_reversal` returns (None = not yet booked).
    """
    import verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency as ri

    return patch.multiple(
        ri,
        find_booked_payment=lambda payment_id: forward,
        find_booked_reversal=lambda key: reversal,
    )


def _make_service(idempotency_manager=None):
    """Construct the wrapper without running __init__ (no live setup)."""
    svc = object.__new__(wws.UnifiedWebhookWrapperService)
    svc.logger = wws.MollieLogger("test_unified_webhook_wrapper")
    svc._debug_mode = False
    svc.idempotency_manager = idempotency_manager or MagicMock()
    return svc


class TestProcessReversalWebhookValidation(FrappeTestCase):
    """Input-validation branches (no DB needed)."""

    def setUp(self):
        self.svc = _make_service()

    def test_invalid_reversal_type(self):
        result = self.svc.process_reversal_webhook("tr_1", "re_1", 10.0, "bogus")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid reversal_type", result["message"])

    def test_zero_amount_rejected(self):
        result = self.svc.process_reversal_webhook("tr_1", "re_1", 0.0, "refund")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid amount", result["message"])

    def test_negative_amount_rejected(self):
        result = self.svc.process_reversal_webhook("tr_1", "re_1", -5.0, "refund")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid amount", result["message"])

    def test_original_payment_missing(self):
        # Idempotency reports no Payment Entry -> cannot process reversal.
        state = PaymentIdempotencyCheckResult("tr_1")
        state.payment_entry_exists = False
        self.svc.idempotency_manager.check_payment_processing_state.return_value = state
        result = self.svc.process_reversal_webhook("tr_1", "re_1", 10.0, "refund")
        self.assertEqual(result["status"], "error")
        self.assertIn("original payment", result["message"])
        self.assertEqual(result["refund_id"], "re_1")


class TestProcessReversalWebhookIdempotency(FrappeTestCase):
    """Already-processed reversal short-circuits (real DB query, no match)."""

    def setUp(self):
        self.svc = _make_service()

    def tearDown(self):
        frappe.db.rollback()

    def test_already_processed_returns_idempotent(self):
        """A reversal already booked as ANY artefact short-circuits."""
        with _booked(reversal=("Payment Entry", "PE-EXISTING-001")):
            result = self.svc.process_reversal_webhook("tr_idem", "re_idem", 10.0, "refund")

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["existing_reference"], "PE-EXISTING-001")

    def test_booking_without_its_donation_is_ignored_and_named(self):
        """Something posted money against this payment, and the Donation is gone.

        Previously this was "payment exists per the idempotency manager, no
        Donation" and was reported with the same "not found" used for a payment
        never seen. It is now reached through a real forward booking and refused as
        inconsistent state, naming the artefact -- the mislabelling that hid this
        whole bug class is exactly this kind of shared, uninformative wording.
        """
        with (
            _booked(forward=("donation", "Journal Entry", "ACC-JV-ORPHAN")),
            patch(
                "verenigingen.verenigingen_payments.mollie.utils.webhook_utilities.get_donation_by_payment_id",
                return_value=None,
            ),
        ):
            result = self.svc.process_reversal_webhook("tr_nodon", "re_x", 10.0, "refund")

        self.assertEqual(result["status"], "ignored")
        self.assertIn("ACC-JV-ORPHAN", result["message"])
        self.assertIn("Donation", result["message"])


class TestProcessReversalWebhookSuccess(FrappeTestCase):
    """Success path: a reversal PE is created and payment history appended."""

    def setUp(self):
        self.svc = _make_service()
        self.donation_name = self._make_submitted_donation("tr_rev_success")

    def tearDown(self):
        frappe.db.rollback()

    def test_refund_creates_pe_and_marks_processed(self):
        donation_doc = frappe.get_doc("Donation", self.donation_name)

        fake_pe = SimpleNamespace(name="PE-REV-001")

        # Forward-booked as a Payment Entry, so the reversal mirrors it as one.
        with (
            _booked(),
            patch(
                "verenigingen.verenigingen_payments.mollie.utils.webhook_utilities.get_donation_by_payment_id",
                return_value=donation_doc,
            ),
            patch(
                "verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator.create_unified_payment_entry",
                return_value=fake_pe,
            ),
        ):
            result = self.svc.process_reversal_webhook(
                "tr_rev_success", "re_succ", 10.0, "refund", reversal_date="2026-01-15"
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["refund_id"], "re_succ")
        self.assertEqual(result["payment_entry_id"], "PE-REV-001")
        # The unified manager must be told the refund is processed.
        self.svc.idempotency_manager.mark_refund_processed.assert_called_once()

        # The reversal payment-history row was appended to the donation in memory
        # with negative amount + Refunded status (Link validation against the
        # fake PE is not the subject of this test).
        rev_rows = [p for p in donation_doc.payments if p.mollie_payment_id == "re_succ"]
        self.assertEqual(len(rev_rows), 1)
        self.assertEqual(float(rev_rows[0].amount), -10.0)
        self.assertEqual(rev_rows[0].payment_status, "Refunded")

    def test_chargeback_marks_chargeback_processed(self):
        donation_doc = frappe.get_doc("Donation", self.donation_name)

        fake_pe = SimpleNamespace(name="PE-CHB-001")

        with (
            _booked(),
            patch(
                "verenigingen.verenigingen_payments.mollie.utils.webhook_utilities.get_donation_by_payment_id",
                return_value=donation_doc,
            ),
            patch(
                "verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator.create_unified_payment_entry",
                return_value=fake_pe,
            ),
        ):
            result = self.svc.process_reversal_webhook(
                "tr_rev_success",
                "chb_succ",
                15.0,
                "chargeback",
                reason={"code": "AC01", "description": "no mandate"},
            )

        self.assertEqual(result["status"], "success")
        self.svc.idempotency_manager.mark_chargeback_processed.assert_called_once()
        chb_rows = [p for p in donation_doc.payments if p.mollie_payment_id == "chb_succ"]
        self.assertEqual(len(chb_rows), 1)
        self.assertEqual(chb_rows[0].payment_status, "Chargeback")

    def _make_submitted_donation(self, payment_id):
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Reversal Test Donor"
        donor.donor_type = "Individual"
        donor.donor_email = "reversal-test-donor@example.com"
        donor.flags.ignore_mandatory = True
        donor.insert(ignore_permissions=True)

        donation = frappe.new_doc("Donation")
        donation.donor = donor.name
        donation.amount = 10
        donation.donation_date = frappe.utils.nowdate()
        donation.mode_of_payment = frappe.db.get_value("Mode of Payment", {}, "name") or "Cash"
        donation.payment_id = payment_id
        donation.paid = 1
        donation.flags.ignore_mandatory = True
        donation.insert(ignore_permissions=True)
        return donation.name


class TestProcessRefundChargebackDelegation(FrappeTestCase):
    """process_refund_webhook / process_chargeback_webhook extract IDs + delegate."""

    def setUp(self):
        self.svc = _make_service()

    def test_refund_delegates_with_extracted_id(self):
        captured = {}

        def fake_reversal(**kwargs):
            captured.update(kwargs)
            return {"status": "success"}

        self.svc.process_reversal_webhook = fake_reversal
        self.svc.process_refund_webhook(
            "tr_1", {"id": "re_99", "amount": {"value": "12.00"}, "created_at": "2026-02-02T10:00:00+00:00"}
        )
        self.assertEqual(captured["reversal_id"], "re_99")
        self.assertEqual(captured["reversal_type"], "refund")
        self.assertEqual(captured["amount"], 12.0)
        self.assertEqual(captured["reversal_date"], "2026-02-02")

    def test_refund_extracts_nested_id(self):
        captured = {}
        self.svc.process_reversal_webhook = lambda **kw: captured.update(kw) or {"status": "ok"}
        self.svc.process_refund_webhook("tr_1", {"refund": {"id": "re_nested"}})
        self.assertEqual(captured["reversal_id"], "re_nested")

    def test_chargeback_delegates_with_reason(self):
        captured = {}
        self.svc.process_reversal_webhook = lambda **kw: captured.update(kw) or {"status": "ok"}
        self.svc.process_chargeback_webhook(
            "tr_1",
            {"id": "chb_5", "amount": {"value": "30.00"}, "reason": {"code": "AC04"}},
        )
        self.assertEqual(captured["reversal_id"], "chb_5")
        self.assertEqual(captured["reversal_type"], "chargeback")
        self.assertEqual(captured["reason"], {"code": "AC04"})


class TestFetchPaymentFromMollie(FrappeTestCase):
    """_fetch_payment_from_mollie normalizes dict + object payment formats."""

    def setUp(self):
        self.svc = _make_service()

    def _patch_client(self, payment):
        mock_client = MagicMock()
        mock_client.payments.get.return_value = payment
        mock_settings = MagicMock()
        mock_settings.get_mollie_client.return_value = mock_client
        return patch.object(frappe, "get_single", return_value=mock_settings)

    def test_dict_format(self):
        payment = {
            "id": "tr_dict",
            "status": "paid",
            "amount": {"value": "25.00", "currency": "EUR"},
            "description": "d",
            "metadata": {"k": "v"},
            "createdAt": "2026-01-01",
            "paidAt": "2026-01-02",
            "method": "ideal",
        }
        with self._patch_client(payment):
            result = self.svc._fetch_payment_from_mollie("tr_dict")
        self.assertEqual(result["id"], "tr_dict")
        self.assertEqual(result["status"], "paid")
        self.assertEqual(result["amount"]["value"], "25.00")
        self.assertEqual(result["created_at"], "2026-01-01")
        self.assertEqual(result["paid_at"], "2026-01-02")

    def test_object_format(self):
        payment = SimpleNamespace(
            id="tr_obj",
            status="paid",
            amount=SimpleNamespace(value="50.00", currency="USD"),
            description="d",
            metadata={"a": 1},
            created_at="2026-03-01",
            paid_at="2026-03-02",
            method="creditcard",
        )
        with self._patch_client(payment):
            result = self.svc._fetch_payment_from_mollie("tr_obj")
        self.assertEqual(result["id"], "tr_obj")
        self.assertEqual(result["amount"]["value"], "50.00")
        self.assertEqual(result["amount"]["currency"], "USD")

    def test_object_without_amount_defaults_zero(self):
        payment = SimpleNamespace(
            id="tr_noamt",
            status="open",
            amount=None,
            description=None,
            metadata=None,
            created_at=None,
            paid_at=None,
            method=None,
        )
        with self._patch_client(payment):
            result = self.svc._fetch_payment_from_mollie("tr_noamt")
        self.assertEqual(result["amount"]["value"], "0")
        self.assertEqual(result["amount"]["currency"], "EUR")
        self.assertEqual(result["metadata"], {})

    def test_fetch_error_raises_payment_error(self):
        from verenigingen.verenigingen_payments.mollie.exceptions import MolliePaymentError

        mock_settings = MagicMock()
        mock_settings.get_mollie_client.side_effect = Exception("network down")
        with patch.object(frappe, "get_single", return_value=mock_settings):
            with self.assertRaises(MolliePaymentError):
                self.svc._fetch_payment_from_mollie("tr_err")


class TestProcessPaymentWebhookRouting(FrappeTestCase):
    """process_payment_webhook STEP-0 routing + idempotency branches."""

    def setUp(self):
        self.svc = _make_service()
        self.payment_id = "tr_route"

    def tearDown(self):
        frappe.db.rollback()

    def _patch_router(self, payment_type, route_result):
        from verenigingen.verenigingen_payments.mollie.domain.payment_classification import (
            PaymentType,
        )

        mock_router = MagicMock()
        mock_router.fetch_payment.return_value = {"id": self.payment_id}
        mock_router.classify_payment.return_value = {
            "payment_type": getattr(PaymentType, payment_type),
            "confidence": "high",
            "matched_by": "metadata",
        }
        mock_router.route_payment.return_value = dict(route_result)
        return patch(
            "verenigingen.verenigingen_payments.mollie.services.payment_type_router.get_payment_router",
            return_value=mock_router,
        )

    def test_order_payment_routed(self):
        with self._patch_router("ORDER", {"status": "success", "routed": "order"}):
            result = self.svc.process_payment_webhook(self.payment_id, {})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["routed"], "order")
        self.assertIn("duration_seconds", result)

    def test_dues_payment_routed(self):
        with self._patch_router("DUES", {"status": "success", "routed": "dues"}):
            result = self.svc.process_payment_webhook(self.payment_id, {})
        self.assertEqual(result["routed"], "dues")

    def test_service_unavailable_on_api_check_failure(self):
        """503 branch when refund/chargeback validation failed."""
        from verenigingen.verenigingen_payments.mollie.domain.payment_classification import (
            PaymentType,
        )

        state = PaymentIdempotencyCheckResult(self.payment_id)
        state.refund_check_failed = True
        self.svc.idempotency_manager.check_payment_processing_state.return_value = state

        mock_router = MagicMock()
        mock_router.fetch_payment.return_value = {"id": self.payment_id}
        mock_router.classify_payment.return_value = {
            "payment_type": PaymentType.DONATION,
            "confidence": "low",
            "matched_by": "none",
        }
        frappe.local.response.http_status_code = 200
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.payment_type_router.get_payment_router",
            return_value=mock_router,
        ):
            result = self.svc.process_payment_webhook(self.payment_id, {})

        self.assertEqual(result["status"], "service_unavailable")
        self.assertEqual(frappe.local.response.http_status_code, 503)

    def test_classification_failure_falls_through_to_idempotency(self):
        """If classification raises, falls back to donation/idempotency path."""
        state = PaymentIdempotencyCheckResult(self.payment_id)
        state.payment_entry_exists = True
        state.payment_history_updated = True
        state.donation_status_updated = True
        # Fully processed -> _handle_fully_processed_payment
        self.svc.idempotency_manager.check_payment_processing_state.return_value = state

        mock_router = MagicMock()
        mock_router.fetch_payment.side_effect = Exception("classify boom")
        with (
            patch(
                "verenigingen.verenigingen_payments.mollie.services.payment_type_router.get_payment_router",
                return_value=mock_router,
            ),
            patch.object(wws, "find_donation_for_payment_by_id", return_value=None),
        ):
            result = self.svc.process_payment_webhook(self.payment_id, {})

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["idempotent"])

    def test_top_level_exception_returns_error(self):
        # get_payment_router import succeeds but check_payment_processing_state raises.
        self.svc.idempotency_manager.check_payment_processing_state.side_effect = Exception("kaboom")
        mock_router = MagicMock()
        mock_router.fetch_payment.side_effect = Exception("classify boom")
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.payment_type_router.get_payment_router",
            return_value=mock_router,
        ):
            result = self.svc.process_payment_webhook(self.payment_id, {})
        self.assertEqual(result["status"], "error")
        self.assertIn("kaboom", result["message"])


class TestHandleNewPaymentSkippedStatus(FrappeTestCase):
    """_handle_new_payment_processing skips non-paid statuses."""

    def setUp(self):
        self.svc = _make_service()

    def test_unpaid_status_skipped(self):
        state = PaymentIdempotencyCheckResult("tr_unpaid")
        with patch.object(self.svc, "_fetch_payment_from_mollie", return_value={"status": "open"}):
            result = self.svc._handle_new_payment_processing("tr_unpaid", {}, state, 0.0)
        self.assertEqual(result["status"], "skipped")

    def test_paid_but_no_donation_errors(self):
        state = PaymentIdempotencyCheckResult("tr_nodonation")
        with (
            patch.object(self.svc, "_fetch_payment_from_mollie", return_value={"status": "paid"}),
            patch.object(wws, "find_donation_for_payment_by_id", return_value=None),
        ):
            result = self.svc._handle_new_payment_processing("tr_nodonation", {}, state, 0.0)
        self.assertEqual(result["status"], "error")
        self.assertIn("No donation found", result["message"])


class TestFindDonationForPaymentById(FrappeTestCase):
    def tearDown(self):
        frappe.db.rollback()

    def test_returns_none_when_absent(self):
        self.assertIsNone(wws.find_donation_for_payment_by_id("tr_absent_zzz"))

    def test_returns_doc_when_present(self):
        donation_name = self._make_donation_with_payment_id("tr_findme")
        found = wws.find_donation_for_payment_by_id("tr_findme")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, donation_name)

    def _make_donation_with_payment_id(self, payment_id):
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Find Test Donor"
        donor.donor_type = "Individual"
        donor.donor_email = "find-test-donor@example.com"
        donor.flags.ignore_mandatory = True
        donor.insert(ignore_permissions=True)

        donation = frappe.new_doc("Donation")
        donation.donor = donor.name
        donation.amount = 5
        donation.donation_date = frappe.utils.nowdate()
        donation.mode_of_payment = frappe.db.get_value("Mode of Payment", {}, "name") or "Cash"
        donation.payment_id = payment_id
        donation.flags.ignore_mandatory = True
        donation.insert(ignore_permissions=True)
        return donation.name


if __name__ == "__main__":
    unittest.main()
