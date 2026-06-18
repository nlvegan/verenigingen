# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Endpoint-level tests for the ING Checkout webhook handlers
(handle_payment / handle_mandate / handle_direct_debit in api/webhook.py).

The prior test file omitted these "because frappe.request is a LocalProxy that
cannot be easily mocked" -- but it CAN be driven by assigning frappe.local.request
to a request-like object. We do that here and assert the full orchestration:
rate limiting (429), empty body (400), signature failure (401), invalid JSON
(400), idempotent duplicate short-circuit, missing 'object' (400), the success
path, and the savepoint-rollback-then-500 on a processing exception.

The genuine boundaries -- rate limiter, signature verifier, duplicate check,
webhook log writer, and the inner _process_* functions -- are stubbed so each
test isolates one orchestration branch. The HTTP-status side effects on
frappe.local.response are real and asserted.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ing_checkout.api import webhook as wh

MODULE = "verenigingen.verenigingen_payments.ing_checkout.api.webhook"


class WebhookEndpointTestBase(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # Reset response and form_dict, install a request-like object.
        frappe.local.response = frappe._dict({})
        frappe.local.request_ip = "203.0.113.1"
        frappe.local.form_dict = frappe._dict({})
        self._orig_request = getattr(frappe.local, "request", None)
        self.addCleanup(self._restore_request)

    def _restore_request(self):
        frappe.local.request = self._orig_request

    def _install_request(self, body=b'{"id": "EX-1", "object": {"reference": "X"}}', headers=None):
        headers = headers or {}
        frappe.local.request = SimpleNamespace(
            method="POST",
            path="/api/method/ing_checkout_webhook",
            get_data=lambda: body,
            headers=SimpleNamespace(get=lambda key, default=None: headers.get(key, default)),
        )

    def _allow_rate_limit(self):
        limiter = MagicMock()
        limiter.check_rate_limit.return_value = (True, None)
        return patch(f"{MODULE}.get_webhook_rate_limiter", return_value=limiter)

    def _pass_signature(self):
        return patch(f"{MODULE}.verify_ing_checkout_webhook", return_value=True)

    def _not_duplicate(self):
        return patch(f"{MODULE}.is_duplicate_webhook", return_value=False)

    def _silence_log(self):
        return patch(f"{MODULE}.log_webhook", return_value="LOG-1")

    def status_code(self):
        return frappe.local.response.get("http_status_code")


class TestSafeSavepointName(FrappeTestCase):
    """Regression: Pay.nl IDs contain hyphens which break SAVEPOINT <name> SQL."""

    def test_hyphens_replaced_with_underscore(self):
        # Without sanitization, "ing_payment_EX-1234-5678" is invalid SQL and the
        # webhook crashes at frappe.db.savepoint() before processing anything.
        name = wh._safe_savepoint_name("ing_payment", "EX-1234-5678")
        self.assertEqual(name, "ing_payment_EX_1234_5678")
        self.assertRegex(name, r"^[0-9A-Za-z_]+$")

    def test_none_identifier_safe(self):
        self.assertEqual(wh._safe_savepoint_name("ing_mandate", None), "ing_mandate_unknown")

    def test_dotted_now_timestamp_sanitized(self):
        # Fallback IDs use frappe.utils.now() ("2026-06-18 18:05:48.123456").
        name = wh._safe_savepoint_name("ing_debit", "2026-06-18 18:05:48.123456")
        self.assertRegex(name, r"^[0-9A-Za-z_]+$")


class TestHandlePayment(WebhookEndpointTestBase):
    def test_rate_limited_returns_429(self):
        limiter = MagicMock()
        limiter.check_rate_limit.return_value = (False, "too many")
        self._install_request()
        with patch(f"{MODULE}.get_webhook_rate_limiter", return_value=limiter):
            result = wh.handle_payment()
        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(self.status_code(), 429)

    def test_empty_body_returns_400(self):
        self._install_request(body=b"")
        with self._allow_rate_limit():
            result = wh.handle_payment()
        self.assertEqual(self.status_code(), 400)
        self.assertIsInstance(result, dict)

    def test_signature_failure_returns_401(self):
        self._install_request()
        sig_fail = patch(
            f"{MODULE}.verify_ing_checkout_webhook",
            side_effect=wh.INGCheckoutWebhookError("bad sig", {"r": "x"}),
        )
        with self._allow_rate_limit(), sig_fail:
            wh.handle_payment()
        self.assertEqual(self.status_code(), 401)

    def test_invalid_json_returns_400(self):
        self._install_request(body=b"not-json{")
        with self._allow_rate_limit(), self._pass_signature():
            wh.handle_payment()
        self.assertEqual(self.status_code(), 400)

    def test_duplicate_short_circuits(self):
        self._install_request(body=b'{"id": "EX-DUP", "object": {"reference": "X"}}')
        with self._allow_rate_limit(), self._pass_signature(), patch(
            f"{MODULE}.is_duplicate_webhook", return_value=True
        ):
            result = wh.handle_payment()
        self.assertEqual(result["status"], "duplicate")

    def test_missing_object_returns_400(self):
        self._install_request(body=b'{"id": "EX-NOOBJ"}')
        with self._allow_rate_limit(), self._pass_signature(), self._not_duplicate(), self._silence_log():
            wh.handle_payment()
        self.assertEqual(self.status_code(), 400)

    def test_success_path(self):
        self._install_request(
            body=b'{"id": "EX-OK", "object": {"reference": "SINV:X", "status": {"code": 100, "action": "PAID"}}}'
        )
        with self._allow_rate_limit(), self._pass_signature(), self._not_duplicate(), self._silence_log(), patch(
            f"{MODULE}._process_payment_webhook",
            return_value={"transaction_name": "T-1", "status": "Paid"},
        ) as mock_proc:
            result = wh.handle_payment()
        mock_proc.assert_called_once()
        # Success response carries the order id + processing result.
        self.assertIn("EX-OK", str(result))

    def test_processing_exception_rolls_back_and_500(self):
        self._install_request(body=b'{"id": "EX-ERR", "object": {"reference": "X", "status": {}}}')
        with self._allow_rate_limit(), self._pass_signature(), self._not_duplicate(), self._silence_log(), patch(
            f"{MODULE}._process_payment_webhook", side_effect=RuntimeError("kaboom")
        ), patch(
            "frappe.db.rollback"
        ) as mock_rollback:
            wh.handle_payment()
        # Savepoint rollback was attempted, and the outer handler reported 500.
        mock_rollback.assert_called()
        self.assertEqual(self.status_code(), 500)


class TestHandleMandate(WebhookEndpointTestBase):
    def test_rate_limited_429(self):
        limiter = MagicMock()
        limiter.check_rate_limit.return_value = (False, "nope")
        self._install_request()
        with patch(f"{MODULE}.get_webhook_rate_limiter", return_value=limiter):
            result = wh.handle_mandate()
        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(self.status_code(), 429)

    def test_empty_body_400(self):
        self._install_request(body=b"")
        with self._allow_rate_limit():
            wh.handle_mandate()
        self.assertEqual(self.status_code(), 400)

    def test_signature_failure_401(self):
        self._install_request()
        with self._allow_rate_limit(), patch(
            f"{MODULE}.verify_ing_checkout_webhook",
            side_effect=wh.INGCheckoutWebhookError("bad"),
        ):
            wh.handle_mandate()
        self.assertEqual(self.status_code(), 401)

    def test_duplicate(self):
        self._install_request(body=b'{"id": "MAND-DUP", "object": {"status": "active"}}')
        with self._allow_rate_limit(), self._pass_signature(), patch(
            f"{MODULE}.is_duplicate_webhook", return_value=True
        ):
            result = wh.handle_mandate()
        self.assertEqual(result["status"], "duplicate")

    def test_success(self):
        self._install_request(body=b'{"id": "MAND-OK", "object": {"status": "active"}}')
        with self._allow_rate_limit(), self._pass_signature(), self._not_duplicate(), self._silence_log(), patch(
            f"{MODULE}._process_mandate_webhook",
            return_value={"handled": True, "action": "status_updated"},
        ) as mock_proc:
            result = wh.handle_mandate()
        mock_proc.assert_called_once()
        self.assertIn("MAND-OK", str(result))

    def test_processing_exception_500(self):
        self._install_request(body=b'{"id": "MAND-ERR", "object": {"status": "x"}}')
        with self._allow_rate_limit(), self._pass_signature(), self._not_duplicate(), self._silence_log(), patch(
            f"{MODULE}._process_mandate_webhook", side_effect=RuntimeError("boom")
        ), patch(
            "frappe.db.rollback"
        ) as mock_rollback:
            wh.handle_mandate()
        mock_rollback.assert_called()
        self.assertEqual(self.status_code(), 500)


class TestHandleDirectDebit(WebhookEndpointTestBase):
    def test_rate_limited_429(self):
        limiter = MagicMock()
        limiter.check_rate_limit.return_value = (False, "nope")
        self._install_request()
        with patch(f"{MODULE}.get_webhook_rate_limiter", return_value=limiter):
            result = wh.handle_direct_debit()
        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(self.status_code(), 429)

    def test_empty_body_400(self):
        self._install_request(body=b"")
        with self._allow_rate_limit():
            wh.handle_direct_debit()
        self.assertEqual(self.status_code(), 400)

    def test_invalid_json_400(self):
        self._install_request(body=b"garbage{")
        with self._allow_rate_limit(), self._pass_signature():
            wh.handle_direct_debit()
        self.assertEqual(self.status_code(), 400)

    def test_duplicate(self):
        self._install_request(body=b'{"id": "DEBIT-DUP", "object": {"status": "completed"}}')
        with self._allow_rate_limit(), self._pass_signature(), patch(
            f"{MODULE}.is_duplicate_webhook", return_value=True
        ):
            result = wh.handle_direct_debit()
        self.assertEqual(result["status"], "duplicate")

    def test_success(self):
        self._install_request(body=b'{"id": "DEBIT-OK", "object": {"status": "completed"}}')
        with self._allow_rate_limit(), self._pass_signature(), self._not_duplicate(), self._silence_log(), patch(
            f"{MODULE}._process_direct_debit_webhook",
            return_value={"handled": True, "action": "transaction_updated"},
        ) as mock_proc:
            result = wh.handle_direct_debit()
        mock_proc.assert_called_once()
        self.assertIn("DEBIT-OK", str(result))

    def test_processing_exception_500(self):
        self._install_request(body=b'{"id": "DEBIT-ERR", "object": {"status": "x"}}')
        with self._allow_rate_limit(), self._pass_signature(), self._not_duplicate(), self._silence_log(), patch(
            f"{MODULE}._process_direct_debit_webhook", side_effect=RuntimeError("boom")
        ), patch(
            "frappe.db.rollback"
        ) as mock_rollback:
            wh.handle_direct_debit()
        mock_rollback.assert_called()
        self.assertEqual(self.status_code(), 500)
