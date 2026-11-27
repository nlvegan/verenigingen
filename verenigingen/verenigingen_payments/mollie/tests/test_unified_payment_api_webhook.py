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


def _forget_logged_failures():
    """The dedupe keys live in Redis for an hour, outside the test transaction: clear them so
    a row that an earlier run (or test) already wrote cannot hide the one under test."""
    frappe.cache.delete_keys(unified_payment_api._ERROR_LOG_DEDUPE_PREFIX)


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
        self.addCleanup(setattr, frappe.local, "response", getattr(frappe.local, "response", None))
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
        """A successful service result is acknowledged, not echoed; no 500 is set.

        #1781: the old assertion (``out["status"] == "success"``) pinned the service result
        being handed back to the anonymous caller. The property kept is "success is not a
        failure": 2xx and an ``ok`` body. The control that a failure is NOT ``ok`` is
        test_service_error_result_sets_http_500.
        """
        payload = make_webhook_payload("tr_ok_123", status="paid")
        result_obj = {"status": "success", "message": "processed", "payment_id": "tr_ok_123"}
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(SERVICE_PATH, return_value=_fake_service(return_value=result_obj)):
                    out = unified_payment_api.handle_payment_webhook(payment_id="tr_ok_123")
        self.assertEqual(out, {"status": "ok"})
        self.assertNotIn("tr_ok_123", str(out), "the service result must not be echoed")
        self.assertLess(getattr(frappe.local.response, "http_status_code", None) or 200, 400)

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
        body is the bare ack (no internal detail leaked to caller).

        #1781: the old assertion read ``out["message"] == "Internal processing error"``;
        the property (nothing internal reaches the caller) is kept and made stricter.
        """
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
        self.assertEqual(out, {"status": "error"})
        self.assertNotIn("secret internal detail", str(out))

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


class TestKnownErrorsAreRefusedWith400AndAnAckOnly(EnhancedTestCase):
    """MollieWebhookError / MolliePaymentError map to HTTP 400 and a bare error ack on the
    handler (#1781). Both halves are asserted: the 400 is what a ``>= 500`` threshold in
    ``_ack_with_error_log`` would silently turn into ``ok``."""

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, frappe.local, "response", getattr(frappe.local, "response", None))
        frappe.local.response = frappe._dict()

    def test_payment_handler(self):
        from verenigingen.verenigingen_payments.mollie.exceptions import MolliePaymentError

        cases = {
            "payment": (
                lambda exc: patch(
                    SERVICE_PATH,
                    return_value=types.SimpleNamespace(
                        process_payment_webhook=lambda pid, data: (_ for _ in ()).throw(exc)
                    ),
                ),
                lambda: unified_payment_api.handle_payment_webhook(payment_id="tr_k_1"),
                make_webhook_payload("tr_k_1"),
            ),
        }
        self.expectErrorLog("Mollie", "Webhook")
        for name, (stub, call, payload) in cases.items():
            for exc in (MollieWebhookError("secret-detail"), MolliePaymentError("secret-detail")):
                with self.subTest(handler=name, exc=type(exc).__name__):
                    frappe.local.response = frappe._dict()
                    with install_fake_request(payload), patch(AUTH_PATH), stub(exc):
                        out = call()
                    self.assertEqual(frappe.local.response.http_status_code, 400)
                    self.assertEqual(out, {"status": "error"})


class TestNon2xxErrorLogRowIsDedupedAndBounded(EnhancedTestCase):
    """The non-2xx "Mollie Webhook Processing Error" row is written once per
    (payment id, status) per hour, and the id it logs is cut to 64 characters (#1822).

    An anonymous caller can post failing deliveries at up to the endpoint's rate limit, and
    the id is theirs to make as long as they like; the row used to be written every time,
    with the id whole.
    """

    ROW = "Mollie Webhook Processing Error"

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, frappe.local, "response", getattr(frappe.local, "response", None))
        frappe.local.response = frappe._dict()
        _forget_logged_failures()

    def _fail(self, payment_id, status="error", http=None):
        """Drive a failing delivery. ``http`` stands in for a service that sets its own
        non-2xx (the 503 "Mollie unreachable" path); otherwise ``error`` makes the handler 500."""

        def process(pid, data):
            if http:
                frappe.local.response["http_status_code"] = http
            return {"status": status, "message": f"cannot book {payment_id}"}

        fake = types.SimpleNamespace(process_payment_webhook=process)
        frappe.local.response = frappe._dict()
        with install_fake_request(make_webhook_payload(payment_id)):
            with patch(AUTH_PATH), patch(SERVICE_PATH, return_value=fake):
                return unified_payment_api.handle_payment_webhook(payment_id=payment_id)

    def _processing_error_rows(self):
        return frappe.db.count("Error Log", {"method": self.ROW})

    def test_a_repeated_failure_for_one_id_writes_one_row(self):
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        self.expectErrorLog("Mollie", "Webhook")
        before = self._processing_error_rows()
        for _ in range(3):
            self.assertEqual(self._fail(payment_id), {"status": "error"})
            self.assertEqual(frappe.local.response.http_status_code, 500)
        self.assertEqual(self._processing_error_rows(), before + 1)

    def test_another_id_or_another_status_still_gets_its_own_row(self):
        """Control: the key is (id, status), not a blanket once-per-hour switch."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        self.expectErrorLog("Mollie", "Webhook")
        before = self._processing_error_rows()
        self._fail(payment_id)
        self._fail(f"tr_{frappe.generate_hash(length=10)}")
        self.assertEqual(self._processing_error_rows(), before + 2)
        # Same id, different failure: a 503 (Mollie unreachable) after a 500 is new news.
        self._fail(payment_id, status="service_unavailable", http=503)
        self.assertEqual(self._processing_error_rows(), before + 3)

    def test_a_long_id_is_cut_in_the_logged_row(self):
        long_id = "tr_" + "x" * 500
        self.expectErrorLog("Mollie", "Webhook")
        before = self._processing_error_rows()
        self._fail(long_id)
        self.assertEqual(self._processing_error_rows(), before + 1)
        row = frappe.get_all(
            "Error Log", filters={"method": self.ROW}, fields=["error"], order_by="creation desc", limit=1
        )[0]
        self.assertIn(long_id[:64], row.error)
        self.assertNotIn(long_id[:65], row.error)

    def test_two_long_ids_sharing_a_prefix_are_not_one_failure(self):
        """Control for the dedupe key: it hashes the WHOLE id. Cutting the id to the logged
        length before hashing would fold these two into a single row."""
        prefix = "tr_" + "p" * 100
        self.expectErrorLog("Mollie", "Webhook")
        before = self._processing_error_rows()
        self._fail(prefix + "a" * 400)
        self._fail(prefix + "b" * 400)
        self.assertEqual(self._processing_error_rows(), before + 2)
