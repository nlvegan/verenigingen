"""
LIVE tests for unified_payment_api webhook entry points.

unified_payment_api.handle_payment_webhook is THE live Mollie payment-webhook
handler (webhooks.py and integrations/mollie route to it). These tests exercise
its orchestration contract: input validation, authentication invocation, the
HTTP-status mapping for each outcome (success / service-error->500 /
rate-limit->429 / known-error->400 / unexpected->500), and that it actually
delegates to the unified webhook service.

What is real vs. stubbed:
- The control flow, status-code mapping and error handling in handle_payment_*
  IS the logic under test — it is NOT mocked.
- authenticate_mollie_webhook is patched to a no-op: its real behaviour (rate
  limiting + HMAC signature validation + user context) is covered directly in
  test_webhook_security_live.py and would otherwise require a full HTTP request
  + service-user config. Here we isolate the API-layer orchestration.
- The unified webhook service boundary is replaced with a SimpleNamespace fake
  so we can drive each return shape deterministically (the service's own
  payment-classification/fetch logic needs Mollie API credentials).
"""

import types
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.webhook_rate_limiter import WebhookRateLimitExceeded
from verenigingen.verenigingen_payments.mollie.api import unified_payment_api
from verenigingen.verenigingen_payments.mollie.exceptions import MollieWebhookError
from verenigingen.verenigingen_payments.mollie.tests.fixtures.webhook_fixtures import (
    install_fake_request,
    make_webhook_payload,
)

AUTH_PATH = "verenigingen.verenigingen_payments.mollie.utils.webhook_security.authenticate_mollie_webhook"
SERVICE_PATH = "verenigingen.verenigingen_payments.mollie.api.unified_payment_api.get_unified_webhook_service"


def _fake_service(return_value=None, raises=None):
    """Build a SimpleNamespace fake of the unified webhook service."""

    def process_payment_webhook(payment_id, webhook_data):
        if raises is not None:
            raise raises
        return return_value

    return types.SimpleNamespace(process_payment_webhook=process_payment_webhook)


class TestHandlePaymentWebhook(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # Reset response status between cases so a prior 500 doesn't leak.
        frappe.local.response = frappe._dict()

    def test_missing_payment_id_returns_500(self):
        """No payment id anywhere => the inner frappe.throw is caught by the
        handler's own except Exception, mapped to a generic 500 dict (NOT raised).
        This pins the real handler contract: it never lets an exception escape to
        Mollie un-acknowledged."""
        with install_fake_request("{}"):
            frappe.local.form_dict = frappe._dict()  # truly empty, no id
            out = unified_payment_api.handle_payment_webhook()
        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 500)

    def test_success_returns_service_result_without_error_status(self):
        """A successful service result is returned unchanged; no 500 is set."""
        payload = make_webhook_payload("tr_ok_123", status="paid")
        result_obj = {"status": "success", "message": "processed", "payment_id": "tr_ok_123"}
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(SERVICE_PATH, return_value=_fake_service(return_value=result_obj)):
                    out = unified_payment_api.handle_payment_webhook(payment_id="tr_ok_123")
        self.assertEqual(out["status"], "success")
        self.assertNotEqual(getattr(frappe.local.response, "http_status_code", None), 500)

    def test_service_error_result_sets_http_500(self):
        """A service result with status=='error' triggers a 500 (Mollie retry)."""
        payload = make_webhook_payload("tr_err_123", status="paid")
        result_obj = {"status": "error", "message": "boom"}
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(SERVICE_PATH, return_value=_fake_service(return_value=result_obj)):
                    out = unified_payment_api.handle_payment_webhook(payment_id="tr_err_123")
        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 500)

    def test_rate_limit_returns_429(self):
        """A WebhookRateLimitExceeded from auth maps to HTTP 429 + rate_limited."""
        payload = make_webhook_payload("tr_rl_123")
        with install_fake_request(payload):
            with patch(AUTH_PATH, side_effect=WebhookRateLimitExceeded("too many")):
                out = unified_payment_api.handle_payment_webhook(payment_id="tr_rl_123")
        self.assertEqual(out["status"], "rate_limited")
        self.assertEqual(frappe.local.response.http_status_code, 429)

    def test_known_webhook_error_returns_400(self):
        """A MollieWebhookError from the service maps to HTTP 400."""
        payload = make_webhook_payload("tr_400_123")
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(
                    SERVICE_PATH,
                    return_value=_fake_service(raises=MollieWebhookError("bad webhook")),
                ):
                    out = unified_payment_api.handle_payment_webhook(payment_id="tr_400_123")
        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 400)

    def test_unexpected_exception_returns_500_and_generic_message(self):
        """An unexpected exception is caught, logged, mapped to 500, and the
        message is the generic one (no internal detail leaked to caller)."""
        payload = make_webhook_payload("tr_500_123")
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(
                    SERVICE_PATH,
                    return_value=_fake_service(raises=RuntimeError("secret internal detail")),
                ):
                    out = unified_payment_api.handle_payment_webhook(payment_id="tr_500_123")
        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 500)
        self.assertEqual(out["message"], "Internal processing error")
        self.assertNotIn("secret internal detail", out["message"])

    def test_payment_id_falls_back_to_form_dict(self):
        """When no explicit arg is given, the id is taken from form_dict['id']."""
        payload = make_webhook_payload("tr_formdict_777", status="paid")
        captured = {}

        def process(payment_id, webhook_data):
            captured["payment_id"] = payment_id
            return {"status": "success"}

        fake = types.SimpleNamespace(process_payment_webhook=process)
        with install_fake_request(payload):
            # install_fake_request already populated form_dict['id'] from payload
            with patch(AUTH_PATH):
                with patch(SERVICE_PATH, return_value=fake):
                    unified_payment_api.handle_payment_webhook()
        self.assertEqual(captured["payment_id"], "tr_formdict_777")


class TestHandleRefundWebhook(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.local.response = frappe._dict()

    def test_empty_payload_returns_500(self):
        """An empty request body after auth => the inner throw is caught by
        except Exception and mapped to a 500 dict (handler never re-raises)."""
        with install_fake_request(""):
            with patch(AUTH_PATH):
                out = unified_payment_api.handle_refund_webhook()
        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 500)

    def test_missing_ids_returns_error_response(self):
        """Payload missing refund/payment ids => standardized error response.

        This exercises the real id-extraction + standardized_webhook_response
        path (no service stub needed; the function returns before touching it).
        """
        payload = '{"resource":"refund"}'  # no id, no refund id
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                out = unified_payment_api.handle_refund_webhook()
        self.assertEqual(out["status"], "error")
        self.assertIn("Missing", out["message"])

    def test_rate_limit_returns_429(self):
        payload = '{"id":"tr_x","_links":{}}'
        with install_fake_request(payload):
            with patch(AUTH_PATH, side_effect=WebhookRateLimitExceeded("slow down")):
                out = unified_payment_api.handle_refund_webhook()
        self.assertEqual(out["status"], "rate_limited")
        self.assertEqual(frappe.local.response.http_status_code, 429)


class TestHandleChargebackWebhook(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.local.response = frappe._dict()

    def test_empty_payload_returns_500(self):
        """Empty body after auth => caught by except Exception => 500 dict."""
        with install_fake_request(""):
            with patch(AUTH_PATH):
                out = unified_payment_api.handle_chargeback_webhook()
        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 500)

    def test_rate_limit_returns_429(self):
        payload = '{"id":"tr_cb_1"}'
        with install_fake_request(payload):
            with patch(AUTH_PATH, side_effect=WebhookRateLimitExceeded("slow down")):
                out = unified_payment_api.handle_chargeback_webhook()
        self.assertEqual(out["status"], "rate_limited")
        self.assertEqual(frappe.local.response.http_status_code, 429)

    def test_service_result_returned(self):
        """A normal chargeback payload delegates to the unified service and the
        service result is returned verbatim.

        REGRESSION GUARD: handle_chargeback_webhook previously imported a class
        name that does not exist (WebhookWrapperServiceUnified) and called
        process_chargeback_webhook with a single positional arg, so every
        chargeback webhook hit an ImportError caught by `except Exception` and
        silently returned a 500 — no chargeback was ever recorded. This test
        patches the REAL class name (UnifiedWebhookWrapperService) and asserts the
        method is invoked with (payment_id, chargeback_data); it fails (AttributeError
        on the patch target, or wrong-arity call) against the pre-fix code."""
        payload = '{"id":"tr_cb_2","status":"charged_back","reason":"fraud"}'
        service_result = {"status": "success", "message": "chargeback recorded"}
        SVC = (
            "verenigingen.verenigingen_payments.mollie.services."
            "webhook_wrapper_service_unified.UnifiedWebhookWrapperService"
        )
        captured = {}

        def process_chargeback_webhook(payment_id, chargeback_data):
            captured["payment_id"] = payment_id
            captured["chargeback_data"] = chargeback_data
            return service_result

        fake = types.SimpleNamespace(process_chargeback_webhook=process_chargeback_webhook)
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(SVC, return_value=fake):
                    out = unified_payment_api.handle_chargeback_webhook()
        self.assertEqual(out, service_result)
        # The payment id must be extracted from the body and passed positionally,
        # alongside the full parsed chargeback dict.
        self.assertEqual(captured["payment_id"], "tr_cb_2")
        self.assertEqual(captured["chargeback_data"]["reason"], "fraud")
