"""
Wiring tests for the PaymentLogger structured-logging adoption.

``TestWebhookReceivedLogging`` (Task 4) asserts ``log_webhook_received`` fires
once at the genuine live webhook entry point for each gateway. ``TestPaymentInitiatedLogging``
(Task 5) asserts ``log_payment_initiated`` fires at the gateway-agnostic
``PaymentHook.initiate_payment`` chokepoint on a successful normalized result.
They are deliberately scoped to the entry-point logging only: the downstream
processing collaborators and request/auth/SDK context are stubbed at their
module boundary so ONLY the entry-point wiring under test is exercised.

Canonical convenience functions:
    verenigingen.verenigingen_payments.utils.payment_services.logging_utils.log_webhook_received
    verenigingen.verenigingen_payments.utils.payment_services.logging_utils.log_payment_initiated
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestWebhookReceivedLogging(VereningingenTestCase):
    """Assert log_webhook_received is wired at the Mollie and ING webhook entries."""

    def test_mollie_webhook_logs_received(self):
        """The live Mollie webhook entry (unified handle_payment_webhook) logs receipt.

        Every configured Mollie webhook URL (webhooks.handle_mollie_payment_webhook /
        mollie_payment_webhook / handle_unified_webhook) funnels into
        unified_payment_api.handle_payment_webhook, which does the real processing.
        That is the genuine entry chokepoint, so the log lives there.
        """
        from verenigingen.verenigingen_payments.mollie.api import unified_payment_api as upa

        # Mock justified: stub the auth (integration boundary) + the downstream
        # webhook-processing service so only the entry-point log_webhook_received
        # wiring is exercised. log_webhook_received is the event under test.
        fake_service = MagicMock()
        fake_service.process_payment_webhook.return_value = {"status": "ok"}

        with patch.object(upa, "log_webhook_received") as mock_log, patch(
            "verenigingen.verenigingen_payments.mollie.utils.webhook_security.authenticate_mollie_webhook"
        ), patch.object(upa, "get_unified_webhook_service", return_value=fake_service):
            try:
                upa.handle_payment_webhook(payment_id="tr_webhook_logtest_1")
            except Exception:
                # Downstream may still raise in some environments; we only assert
                # the entry-point log fired.
                pass

        mock_log.assert_called_once()
        # Confirm it logged the Mollie webhook type and the payment id.
        _, kwargs = mock_log.call_args
        self.assertEqual(kwargs.get("webhook_type"), "mollie")
        self.assertEqual(kwargs.get("webhook_id"), "tr_webhook_logtest_1")

    def test_ing_webhook_logs_received(self):
        """The live ING (Pay.nl) payment webhook entry (handle_payment) logs receipt."""
        import json

        from verenigingen.verenigingen_payments.ing_checkout.api import webhook as ing_webhook

        payload = {
            "event": "status_changed",
            "type": "order",
            "id": "EX-1234-5678-9012",
            "object": {
                "id": "EX-1234-5678-9012",
                "reference": "SINV:ACC-SINV-2025-00001",
                "status": {"code": 100, "action": "PAID"},
                "amount": {"value": 2500, "currency": "EUR"},
            },
        }
        raw = json.dumps(payload).encode("utf-8")

        request = MagicMock()
        request.get_data.return_value = raw
        request.data = raw
        request.method = "POST"
        request.headers = {}

        rl = MagicMock()
        rl.check_rate_limit.return_value = (True, None)

        # Mock justified: stub the request/signature/idempotency/rate-limit
        # integration boundaries + the downstream _process_payment_webhook so
        # only the entry-point log_webhook_received wiring is exercised.
        with patch.object(ing_webhook, "log_webhook_received") as mock_log, patch.object(
            ing_webhook.frappe, "request", request
        ), patch.object(ing_webhook, "verify_ing_checkout_webhook"), patch.object(
            ing_webhook, "is_duplicate_webhook", return_value=False
        ), patch.object(
            ing_webhook, "get_webhook_rate_limiter", return_value=rl
        ), patch.object(
            ing_webhook, "log_webhook"
        ), patch.object(
            ing_webhook, "_process_payment_webhook", return_value={"status": "ok"}
        ):
            frappe.local.form_dict = frappe._dict({"id": "EX-1234-5678-9012"})
            try:
                ing_webhook.handle_payment()
            except Exception:
                pass

        mock_log.assert_called_once()
        _, kwargs = mock_log.call_args
        self.assertEqual(kwargs.get("webhook_type"), "ing_checkout")
        self.assertEqual(kwargs.get("webhook_id"), "EX-1234-5678-9012")


class TestPaymentInitiatedLogging(VereningingenTestCase):
    """Assert log_payment_initiated fires at the gateway-agnostic chokepoint."""

    def test_initiate_payment_logs_payment_initiated(self):
        """A successful initiation logs payment_initiated with amount + method.

        PaymentHook.initiate_payment is the gateway-agnostic chokepoint: it
        validates input, resolves the gateway, processes, then normalizes the
        response. The log fires on a successful normalized result carrying a
        payment_id (here the Mollie-style redirect path).
        """
        from verenigingen.verenigingen_payments.hooks import payment_hook as ph

        class _FakeGateway:
            def process_payment(self, ref_doc, form_data):
                # Mollie-style redirect_required → normalizes to success + payment_id.
                return {
                    "status": "redirect_required",
                    "payment_url": "https://pay.example/redirect",
                    "payment_id": "tr_init_1",
                }

        member = self.create_test_member(first_name="PayInit")

        # Mock justified: PaymentGatewayFactory.get_gateway is the SDK boundary;
        # get_available_methods avoids env-dependent gateway config. The method
        # availability check and log_payment_initiated wiring run for real.
        with patch.object(
            ph.PaymentGatewayFactory, "get_gateway", return_value=_FakeGateway()
        ), patch.object(
            ph.PaymentHook, "get_available_methods", return_value=[{"id": "mollie"}]
        ), patch.object(ph, "log_payment_initiated") as mock_log:
            result = ph.PaymentHook.initiate_payment(
                method="mollie",
                amount=25.0,
                reference_doctype="Member",
                reference_name=member.name,
                payer_info={"email": "payinit@example.com"},
                redirect_urls={"success": "/ok", "cancel": "/no"},
            )

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("payment_id"), "tr_init_1")
        mock_log.assert_called_once()
        called = list(mock_log.call_args.args) + list((mock_log.call_args.kwargs or {}).values())
        self.assertIn("tr_init_1", called)
        self.assertIn(25.0, called)
        self.assertIn("mollie", called)
