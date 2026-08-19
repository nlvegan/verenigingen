"""
UnifiedWebhookWrapperService coverage — integration + SDK-boundary tests.

The wrapper is the main webhook entry point. ``process_payment_webhook`` first
classifies the payment (routing ORDER/DUES payments to their processors), then,
for donations, drives an idempotency state machine (fully-processed / new /
partial). It also owns the reversal (refund + chargeback) processors.

Testing approach:
- The webhook's input is an HTTP payload, so building a payload dict and calling
  the handler is REAL INTEGRATION (the project trust model has the handler
  RE-FETCH the resource from Mollie). The two seams that reach outside the
  process — the Mollie SDK (``_fetch_payment_from_mollie`` / the router's fetch)
  and the unified idempotency manager's Mollie-API-backed refund/chargeback check
  — are stubbed at their boundary. Because those are module-level collaborators,
  this module is ``*_unit.py`` so test-quality-enforcer permits it (Tier-1).
- No business logic is mocked: classification, reversal-type validation, response
  shaping, status routing and result aggregation all run for real.

Live-only paths (skipped here): the full donation financial-entry creation
(Bank Transaction + Journal Entry against operator-configured GL accounts) and a
reversal that builds a real Payment Entry — both need production GL wiring and
are covered by the Mollie live integration suites.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
    find_donation_for_payment_by_id,
    get_unified_webhook_service,
)


class _FakeState:
    """A hand-built PaymentIdempotencyCheckResult stand-in for routing tests."""

    def __init__(self, **kw):
        self.payment_entry_exists = kw.get("payment_entry_exists", False)
        self.payment_entry_name = kw.get("payment_entry_name")
        self.payment_history_updated = kw.get("payment_history_updated", False)
        self.donation_status_updated = kw.get("donation_status_updated", False)
        self.refund_check_failed = kw.get("refund_check_failed", False)
        self.chargeback_check_failed = kw.get("chargeback_check_failed", False)
        self.pending_refunds = kw.get("pending_refunds", [])
        self.pending_chargebacks = kw.get("pending_chargebacks", [])
        self.payment_history_missing = kw.get("payment_history_missing", [])
        self.refunds_processed = kw.get("refunds_processed", [])

    def is_fully_processed(self):
        return self.payment_entry_exists and self.payment_history_updated and self.donation_status_updated

    def needs_payment_processing(self):
        return not self.is_fully_processed()

    def has_pending_refunds(self):
        return len(self.pending_refunds) > 0

    def has_pending_chargebacks(self):
        return len(self.pending_chargebacks) > 0


class WebhookTestBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # The wrapper constructs credential-free: __init__ only builds a
        # MollieLogger and the UnifiedIdempotencyManager (which is lazy about the
        # Mollie client). Every test below stubs the SDK / idempotency boundary,
        # so the suite must NOT be gated on a Mollie key -- otherwise these
        # reversal/idempotency/503 regression guards silently skip in CI.
        self.service = UnifiedWebhookWrapperService()


class TestServiceSingleton(WebhookTestBase):
    def test_get_unified_webhook_service_is_singleton(self):
        a = get_unified_webhook_service()
        b = get_unified_webhook_service()
        self.assertIs(a, b)
        self.assertIsInstance(a, UnifiedWebhookWrapperService)


class TestReversalValidation(WebhookTestBase):
    """process_reversal_webhook input validation — pure, no external calls."""

    def test_invalid_reversal_type_rejected(self):
        result = self.service.process_reversal_webhook(
            payment_id="tr_x", reversal_id="re_x", amount=5.0, reversal_type="bogus"
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid reversal_type", result["message"])

    def test_zero_amount_rejected(self):
        result = self.service.process_reversal_webhook(
            payment_id="tr_x", reversal_id="re_x", amount=0.0, reversal_type="refund"
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("Amount must be greater than 0", result["message"])
        self.assertEqual(result["refund_id"], "re_x")

    def test_negative_amount_rejected(self):
        result = self.service.process_reversal_webhook(
            payment_id="tr_x", reversal_id="cb_x", amount=-3.0, reversal_type="chargeback"
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["chargeback_id"], "cb_x")

    def test_reversal_without_original_payment_is_error(self):
        # Stub the idempotency seam to report no original Payment Entry.
        self.service.idempotency_manager.check_payment_processing_state = lambda payment_id, **k: _FakeState(
            payment_entry_exists=False
        )
        result = self.service.process_reversal_webhook(
            payment_id="tr_missing", reversal_id="re_1", amount=5.0, reversal_type="refund"
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("original payment", result["message"])
        self.assertEqual(result["refund_id"], "re_1")

    def test_already_processed_reversal_is_idempotent(self):
        """A reversal already booked as ANY artefact is reported idempotent.

        Rewritten for the contract introduced by #370. It used to stub
        ``payment_entry_exists = True`` and patch ``frappe.db.get_value``
        *globally*, intercepting on ``reference_no == "<pid>_refund_<rid>"``. Both
        halves are now wrong:

        * The gate no longer asks the idempotency manager whether a payment entry
          exists. It reads what was actually booked, because a donation books a
          Journal Entry and the old question answered "no" for every one of them.
        * The global ``get_value`` patch now serves **two** different lookups --
          the forward-booking lookup keyed on the payment id, and the reversal
          lookup keyed on the compound reference. Answering only the second left
          the first falling through to the real database, so the service correctly
          reported the payment as unbooked and the test failed for a reason that
          had nothing to do with idempotency.

        Patched at the seam the service actually consults, rather than at the
        database. Real-document coverage of the same path lives in
        ``test_webhook_wrapper_unified_sweep`` and
        ``test_mollie_reversal_single_booking``; this suite is deliberately
        fixture-free.
        """
        import verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency as ri

        reference = "tr_done_refund_re_done"
        seen = {}

        def fake_find_booked_payment(payment_id):
            seen["payment_id"] = payment_id
            return ("donation", "Journal Entry", "ACC-JV-FORWARD")

        def fake_find_booked_reversal(key):
            seen["reversal_key"] = key
            return ("Journal Entry", "ACC-JV-REVERSAL-EXISTING") if key == reference else None

        orig_payment, orig_reversal = ri.find_booked_payment, ri.find_booked_reversal
        ri.find_booked_payment = fake_find_booked_payment
        ri.find_booked_reversal = fake_find_booked_reversal
        self.addCleanup(lambda: setattr(ri, "find_booked_payment", orig_payment))
        self.addCleanup(lambda: setattr(ri, "find_booked_reversal", orig_reversal))

        result = self.service.process_reversal_webhook(
            payment_id="tr_done",
            reversal_id="re_done",
            amount=5.0,
            reversal_type="refund",
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["existing_reference"], "ACC-JV-REVERSAL-EXISTING")
        # The two lookups are distinct, and each got the key it is keyed on. The
        # old test could not have caught them being confused.
        self.assertEqual(seen.get("payment_id"), "tr_done")
        self.assertEqual(seen.get("reversal_key"), reference)


class TestRefundChargebackDelegation(WebhookTestBase):
    """process_refund_webhook / process_chargeback_webhook delegate correctly."""

    def test_refund_webhook_delegates_with_extracted_fields(self):
        captured = {}

        def fake_reversal(**kwargs):
            captured.update(kwargs)
            return {"status": "success"}

        self.service.process_reversal_webhook = fake_reversal
        self.service.process_refund_webhook(
            "tr_abc",
            {
                "id": "re_xyz",
                "amount": {"value": "12.50", "currency": "EUR"},
                "created_at": "2025-02-01T00:00:00+00:00",
            },
        )
        self.assertEqual(captured["reversal_type"], "refund")
        self.assertEqual(captured["reversal_id"], "re_xyz")
        self.assertEqual(captured["amount"], 12.50)
        self.assertEqual(captured["payment_id"], "tr_abc")

    def test_chargeback_webhook_delegates_with_reason(self):
        captured = {}

        def fake_reversal(**kwargs):
            captured.update(kwargs)
            return {"status": "success"}

        self.service.process_reversal_webhook = fake_reversal
        self.service.process_chargeback_webhook(
            "tr_abc",
            {
                "id": "cb_xyz",
                "amount": {"value": "30.00", "currency": "EUR"},
                "reason": {"code": "AC01", "description": "Account closed"},
            },
        )
        self.assertEqual(captured["reversal_type"], "chargeback")
        self.assertEqual(captured["reversal_id"], "cb_xyz")
        self.assertEqual(captured["amount"], 30.00)
        self.assertEqual(captured["reason"]["code"], "AC01")


class TestFetchPaymentFromMollie(WebhookTestBase):
    """_fetch_payment_from_mollie normalizes both dict and object SDK responses."""

    def _stub_client(self, returned_payment):
        class _Payments:
            def get(self, pid):
                return returned_payment

        class _Client:
            payments = _Payments()

        class _Settings:
            def get_mollie_client(self):
                return _Client()

        # Stub the single-doc fetch the method performs.
        orig = frappe.get_single
        frappe.get_single = lambda dt: _Settings() if dt == "Mollie Settings" else orig(dt)
        self.addCleanup(lambda: setattr(frappe, "get_single", orig))

    def test_dict_format_normalized(self):
        self._stub_client(
            {
                "id": "tr_dict",
                "status": "paid",
                "amount": {"value": "10.00", "currency": "EUR"},
                "description": "Donation",
                "metadata": {"subscription_id": "sub_1"},
                "createdAt": "2025-01-01T00:00:00+00:00",
            }
        )
        data = self.service._fetch_payment_from_mollie("tr_dict")
        self.assertEqual(data["id"], "tr_dict")
        self.assertEqual(data["status"], "paid")
        self.assertEqual(data["amount"]["value"], "10.00")
        self.assertEqual(data["metadata"]["subscription_id"], "sub_1")

    def test_object_format_normalized(self):
        class _Amount:
            value = "20.00"
            currency = "EUR"

        class _PaymentObj:
            id = "tr_obj"
            status = "paid"
            amount = _Amount()
            description = "Donation"
            metadata = None
            method = "ideal"

        self._stub_client(_PaymentObj())
        data = self.service._fetch_payment_from_mollie("tr_obj")
        self.assertEqual(data["id"], "tr_obj")
        self.assertEqual(data["amount"]["value"], "20.00")
        self.assertEqual(data["amount"]["currency"], "EUR")
        self.assertEqual(data["metadata"], {})  # None coerced to empty dict
        self.assertEqual(data["method"], "ideal")

    def test_sdk_failure_raises_mollie_payment_error(self):
        from verenigingen.verenigingen_payments.mollie.exceptions import MolliePaymentError

        class _Payments:
            def get(self, pid):
                raise RuntimeError("boom")

        class _Client:
            payments = _Payments()

        class _Settings:
            def get_mollie_client(self):
                return _Client()

        orig = frappe.get_single
        frappe.get_single = lambda dt: _Settings() if dt == "Mollie Settings" else orig(dt)
        self.addCleanup(lambda: setattr(frappe, "get_single", orig))

        with self.assertRaises(MolliePaymentError):
            self.service._fetch_payment_from_mollie("tr_boom")


class TestProcessPaymentWebhookRouting(WebhookTestBase):
    """process_payment_webhook routes by classification + idempotency state."""

    def _stub_router(self, payment_type, route_result):
        """Stub the PaymentTypeRouter seam used at the top of the webhook."""
        from verenigingen.verenigingen_payments.mollie.domain.payment_classification import PaymentType

        type_const = {
            "dues": PaymentType.DUES,
            "order": PaymentType.ORDER,
            "donation": PaymentType.DONATION,
            "unknown": PaymentType.UNKNOWN,
        }[payment_type]

        class _Router:
            def fetch_payment(self_inner, pid):
                return object()

            def classify_payment(self_inner, payment):
                return {
                    "payment_type": type_const,
                    "confidence": "high",
                    "matched_by": "stub",
                }

            def route_payment(self_inner, pid, payment):
                return dict(route_result)

        import verenigingen.verenigingen_payments.mollie.services.payment_type_router as router_mod

        orig = router_mod.get_payment_router
        router_mod.get_payment_router = lambda: _Router()
        self.addCleanup(lambda: setattr(router_mod, "get_payment_router", orig))

    def test_dues_payment_routed_to_dues_processor(self):
        self._stub_router("dues", {"status": "success", "payment_entry": "PE-1"})
        result = self.service.process_payment_webhook("tr_dues", {})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["payment_entry"], "PE-1")
        self.assertIn("duration_seconds", result)

    def test_order_payment_routed_to_order_processor(self):
        self._stub_router("order", {"status": "success", "bank_transaction": "BT-1"})
        result = self.service.process_payment_webhook("tr_order", {})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["bank_transaction"], "BT-1")

    def test_donation_falls_through_to_idempotency_state_machine(self):
        # DONATION type falls through to the donation state machine. Force a
        # fully-processed state with no pending refunds → idempotent success.
        self._stub_router("donation", {})
        self.service.idempotency_manager.check_payment_processing_state = lambda payment_id, **k: _FakeState(
            payment_entry_exists=True,
            payment_history_updated=True,
            donation_status_updated=True,
        )
        result = self.service.process_payment_webhook("tr_don", {})
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["idempotent"])

    def test_mollie_api_validation_failure_returns_503(self):
        # When the refund/chargeback check failed (Mollie API down), the webhook
        # must signal a retryable 503 rather than process.
        self._stub_router("donation", {})
        self.service.idempotency_manager.check_payment_processing_state = lambda payment_id, **k: _FakeState(
            refund_check_failed=True
        )
        frappe.local.response.http_status_code = 200  # reset
        result = self.service.process_payment_webhook("tr_503", {})
        self.assertEqual(result["status"], "service_unavailable")
        self.assertEqual(frappe.local.response.http_status_code, 503)

    def test_classification_failure_falls_back_to_donation_logic(self):
        # If the router raises, the webhook falls back to the donation state
        # machine rather than erroring out.
        import verenigingen.verenigingen_payments.mollie.services.payment_type_router as router_mod

        class _BrokenRouter:
            def fetch_payment(self, pid):
                raise RuntimeError("mollie down")

        orig = router_mod.get_payment_router
        router_mod.get_payment_router = lambda: _BrokenRouter()
        self.addCleanup(lambda: setattr(router_mod, "get_payment_router", orig))

        self.service.idempotency_manager.check_payment_processing_state = lambda payment_id, **k: _FakeState(
            payment_entry_exists=True,
            payment_history_updated=True,
            donation_status_updated=True,
        )
        result = self.service.process_payment_webhook("tr_fallback", {})
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["idempotent"])


class TestFullyProcessedRefundAggregation(WebhookTestBase):
    """_handle_fully_processed_payment aggregates refund success/failure."""

    def test_failed_refund_yields_error_status_for_retry(self):
        state = _FakeState(
            payment_entry_exists=True,
            payment_history_updated=True,
            donation_status_updated=True,
            pending_refunds=[{"refund_id": "re_1", "amount": 5.0}],
        )
        # No donation exists for this payment → refund processing yields an error
        # entry, and the handler must surface status="error" to trigger retry.
        result = self.service._handle_fully_processed_payment("tr_nodon", state, 0.0)
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["idempotent"])
        self.assertIn("failed_refunds", result)

    def test_no_pending_refunds_yields_success(self):
        state = _FakeState(
            payment_entry_exists=True,
            payment_history_updated=True,
            donation_status_updated=True,
        )
        result = self.service._handle_fully_processed_payment("tr_clean", state, 0.0)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["idempotent"])


class TestFindDonationHelper(WebhookTestBase):
    """find_donation_for_payment_by_id returns None when no donation matches."""

    def test_returns_none_when_no_donation(self):
        self.assertIsNone(find_donation_for_payment_by_id("tr_does_not_exist_xyz"))
