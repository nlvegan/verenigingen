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

import json
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


class TestHandleRefundWebhook(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, frappe.local, "response", getattr(frappe.local, "response", None))
        frappe.local.response = frappe._dict()
        _forget_logged_failures()

    def test_empty_payload_returns_500(self):
        """An empty request body after auth => the inner throw is caught by
        except Exception and mapped to a 500 dict (handler never re-raises)."""
        with install_fake_request(""):
            with patch(AUTH_PATH):
                out = unified_payment_api.handle_refund_webhook()
        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 500)

    def test_missing_ids_is_refused_with_400_an_ack_only_and_an_error_log_row(self):
        """Payload missing refund/payment ids (#1807): a malformed payload never becomes
        valid on redelivery, so it is refused once, with an explicit 400, the bare ack (the
        caller's own payload is NOT echoed back) and an Error Log row for the operator.

        This exercises the real id-extraction path (no service stub needed; the function
        returns before touching it).
        """
        marker = f"echo-{frappe.generate_hash(length=8)}"
        payload = json.dumps({"resource": "refund", "note": marker})  # no id, no refund id
        before = frappe.db.count("Error Log", {"method": "Mollie Webhook Processing Error"})
        self.expectErrorLog("Mollie", "Webhook")
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                out = unified_payment_api.handle_refund_webhook()
        self.assertEqual(out, {"status": "error"})
        self.assertNotIn(marker, json.dumps(out))
        self.assertEqual(frappe.local.response.http_status_code, 400)
        after = frappe.db.count("Error Log", {"method": "Mollie Webhook Processing Error"})
        self.assertEqual(after, before + 1)

    def test_rate_limit_returns_429(self):
        payload = '{"id":"tr_x","_links":{}}'
        with install_fake_request(payload):
            with patch(AUTH_PATH, side_effect=WebhookRateLimitExceeded("slow down")):
                out = unified_payment_api.handle_refund_webhook()
        self.assertEqual(out["status"], "rate_limited")
        self.assertEqual(frappe.local.response.http_status_code, 429)

    def test_delegates_to_the_unified_reversal_processor(self):
        """A normal refund payload delegates to the unified service.

        REGRESSION GUARD (#370): this endpoint used to book the refund itself, by
        calling `create_refund_payment_entry` directly. That made the **artefact
        depend on the route**: a donation booked forward as a Journal Entry was
        reversed here as a Payment Entry, while the payment-webhook sweep reversed
        the same donation as a Journal Entry. The two routes could not see each
        other's work, which is the double-booking this issue is about.

        The reversal must mirror the artefact the forward payment created, and only
        `process_reversal_webhook` knows what that was. So the endpoint parses and
        delegates -- exactly as `handle_chargeback_webhook` already did.

        The ids are passed from `extract_webhook_ids`, NOT from the service's own
        `refund_data.get("id")`: Mollie's top-level `id` on this payload is the
        **payment** id, and `extract_webhook_ids` is the one that only treats it as
        a refund id when `resource` says so or it starts with `re_`.
        """
        payload = (
            '{"resource":"refund","id":"re_deleg_1",'
            '"payment_id":"tr_deleg_1",'
            '"amount":{"value":"12.50","currency":"EUR"}}'
        )
        service_result = {"status": "success", "message": "refund recorded"}
        SVC = (
            "verenigingen.verenigingen_payments.mollie.services."
            "webhook_wrapper_service_unified.UnifiedWebhookWrapperService"
        )
        captured = {}

        def process_reversal_webhook(payment_id, reversal_id, amount, reversal_type, reversal_date=None):
            captured.update(
                payment_id=payment_id,
                reversal_id=reversal_id,
                amount=amount,
                reversal_type=reversal_type,
            )
            return service_result

        fake = types.SimpleNamespace(process_reversal_webhook=process_reversal_webhook)
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(SVC, return_value=fake):
                    out = unified_payment_api.handle_refund_webhook()

        # #1781: this used to assert the service result came back verbatim, which is the
        # leak. What matters (and is still asserted below) is WHAT the service was called
        # with; the caller only gets the ack.
        self.assertEqual(out, {"status": "ok"})
        self.assertLess(frappe.local.response.get("http_status_code") or 200, 400)
        self.assertNotIn("refund recorded", str(out))
        self.assertEqual(captured.get("payment_id"), "tr_deleg_1")
        self.assertEqual(
            captured.get("reversal_id"),
            "re_deleg_1",
            "the refund id must come from extract_webhook_ids, not from a bare top-level 'id'",
        )
        self.assertEqual(captured.get("reversal_type"), "refund")
        self.assertEqual(captured.get("amount"), 12.50)

    def test_refund_route_passes_mollies_createdAt_as_the_reversal_date_2138(self):
        """#2138: the route read ``created_at``, so a Mollie-shaped refund was booked on today's date."""
        payload = (
            '{"resource":"refund","id":"re_date_1","payment_id":"tr_date_1",'
            '"amount":{"value":"5.00","currency":"EUR"},"createdAt":"2026-03-03T10:00:00+00:00"}'
        )
        SVC = (
            "verenigingen.verenigingen_payments.mollie.services."
            "webhook_wrapper_service_unified.UnifiedWebhookWrapperService"
        )
        captured = {}
        fake = types.SimpleNamespace(
            process_reversal_webhook=lambda **kw: captured.update(kw) or {"status": "success"}
        )
        with install_fake_request(payload), patch(AUTH_PATH), patch(SVC, return_value=fake):
            unified_payment_api.handle_refund_webhook()
        self.assertEqual(captured.get("reversal_date"), "2026-03-03")

    def test_a_booking_failure_returns_500_so_mollie_retries(self):
        """The freed reversal key is worth nothing if nothing comes back to use it.

        On a booking failure the reversal key is deliberately released, so the
        refund can be retried. Mollie only retries on 5xx. Returning the service's
        error dict with a 200 told Mollie the refund was handled, and the sweep is
        then the only remaining route.
        """
        payload = (
            '{"resource":"refund","id":"re_fail_1","payment_id":"tr_fail_1",'
            '"amount":{"value":"5.00","currency":"EUR"}}'
        )
        SVC = (
            "verenigingen.verenigingen_payments.mollie.services."
            "webhook_wrapper_service_unified.UnifiedWebhookWrapperService"
        )
        fake = types.SimpleNamespace(
            process_reversal_webhook=lambda **kw: {"status": "error", "message": "Failed to book refund"}
        )
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(SVC, return_value=fake):
                    out = unified_payment_api.handle_refund_webhook()

        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 500)

    def test_an_ignored_result_stays_2xx(self):
        """Control: redelivering something we deliberately ignored changes nothing.

        Without this, setting 500 unconditionally on any non-success would satisfy
        the test above while making Mollie retry ~10 times for a refund that will be
        ignored identically every time.
        """
        payload = (
            '{"resource":"refund","id":"re_ign_1","payment_id":"tr_ign_1",'
            '"amount":{"value":"5.00","currency":"EUR"}}'
        )
        SVC = (
            "verenigingen.verenigingen_payments.mollie.services."
            "webhook_wrapper_service_unified.UnifiedWebhookWrapperService"
        )
        fake = types.SimpleNamespace(
            process_reversal_webhook=lambda **kw: {"status": "ignored", "message": "nothing to do"}
        )
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(SVC, return_value=fake):
                    out = unified_payment_api.handle_refund_webhook()

        # #1781: the body no longer carries ``ignored``; "stays 2xx" is the property, so the
        # HTTP status is what is asserted (< 400, not just != 500).
        self.assertLess(frappe.local.response.get("http_status_code") or 200, 400)
        self.assertEqual(out, {"status": "ok"})


class TestHandleChargebackWebhook(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, frappe.local, "response", getattr(frappe.local, "response", None))
        frappe.local.response = frappe._dict()
        _forget_logged_failures()

    def test_empty_payload_returns_500(self):
        """Empty body after auth => caught by except Exception => 500 dict."""
        with install_fake_request(""):
            with patch(AUTH_PATH):
                out = unified_payment_api.handle_chargeback_webhook()
        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 500)

    def test_missing_payment_id_is_refused_with_400_and_an_ack_only(self):
        """Same class as the refund endpoint (#1807): a payload that carries no payment id
        never becomes valid on redelivery, so it is refused explicitly with a 400 (as the
        refund endpoint now does, rather than the generic 500), the ack only, and an Error
        Log row."""
        marker = f"echo-{frappe.generate_hash(length=8)}"
        before = frappe.db.count("Error Log", {"method": "Mollie Webhook Processing Error"})
        self.expectErrorLog("Mollie", "Webhook")
        with install_fake_request(json.dumps({"status": "charged_back", "note": marker})):
            with patch(AUTH_PATH):
                out = unified_payment_api.handle_chargeback_webhook()
        self.assertEqual(out, {"status": "error"})
        self.assertNotIn(marker, json.dumps(out))
        self.assertEqual(frappe.local.response.http_status_code, 400)
        after = frappe.db.count("Error Log", {"method": "Mollie Webhook Processing Error"})
        self.assertEqual(after, before + 1)

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
        # #1781: the service result is no longer echoed; the ack is.
        self.assertEqual(out, {"status": "ok"})
        self.assertNotIn("chargeback recorded", str(out))
        # The payment id must be extracted from the body and passed positionally,
        # alongside the full parsed chargeback dict.
        self.assertEqual(captured["payment_id"], "tr_cb_2")
        self.assertEqual(captured["chargeback_data"]["reason"], "fraud")

    def test_a_booking_failure_returns_500_so_mollie_retries(self):
        """A chargeback that could not be booked must not go out as 200.

        This is the refund endpoint's guard, which this endpoint did not have --
        2 of 3 webhook endpoints had it. Mollie retries on 5xx (~10 times over
        26h), and the reversal key is deliberately freed when a booking fails, so
        a 200 spends the redelivery that failure was meant to buy.

        Scope, honestly: that sequence cannot run today. This endpoint is not
        registered with Mollie (payments carry the payment webhook URL only), and
        Mollie posts form-encoded while the handler json.loads() the body, so a
        real chargeback body dies in the outer `except` before reaching here. An
        earlier version of this docstring claimed the guard was "load-bearing
        because of this PR" -- that was reasoning about a path that is dark. The
        guard is correct and is what makes the route safe to wire up; it is not
        today rescuing live money.
        """
        payload = '{"id":"tr_cb_fail","status":"charged_back"}'
        SVC = (
            "verenigingen.verenigingen_payments.mollie.services."
            "webhook_wrapper_service_unified.UnifiedWebhookWrapperService"
        )
        fake = types.SimpleNamespace(
            process_chargeback_webhook=lambda *a, **kw: {
                "status": "error",
                "message": "Failed to book chargeback",
            }
        )
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(SVC, return_value=fake):
                    out = unified_payment_api.handle_chargeback_webhook()

        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 500)

    def test_an_ignored_result_stays_2xx(self):
        """Control: redelivering something deliberately ignored changes nothing.

        Without this, setting 500 on any non-success would satisfy the test above
        while making Mollie retry ~10 times for a chargeback that will be ignored
        identically every time.
        """
        payload = '{"id":"tr_cb_ign","status":"charged_back"}'
        SVC = (
            "verenigingen.verenigingen_payments.mollie.services."
            "webhook_wrapper_service_unified.UnifiedWebhookWrapperService"
        )
        fake = types.SimpleNamespace(
            process_chargeback_webhook=lambda *a, **kw: {"status": "ignored", "message": "nothing to do"}
        )
        with install_fake_request(payload):
            with patch(AUTH_PATH):
                with patch(SVC, return_value=fake):
                    out = unified_payment_api.handle_chargeback_webhook()

        # #1781: HTTP status is the property ("stays 2xx"), not the leaked ``ignored`` body.
        self.assertLess(frappe.local.response.get("http_status_code") or 200, 400)
        self.assertEqual(out, {"status": "ok"})


class TestKnownErrorsAreRefusedWith400AndAnAckOnly(EnhancedTestCase):
    """MollieWebhookError / MolliePaymentError map to HTTP 400 and a bare error ack on ALL
    three handlers (#1781). Both halves are asserted: the 400 is what a ``>= 500`` threshold in
    ``_ack_with_error_log`` would silently turn into ``ok``."""

    SVC = (
        "verenigingen.verenigingen_payments.mollie.services."
        "webhook_wrapper_service_unified.UnifiedWebhookWrapperService"
    )

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, frappe.local, "response", getattr(frappe.local, "response", None))
        frappe.local.response = frappe._dict()

    def test_payment_refund_and_chargeback_handlers(self):
        from verenigingen.verenigingen_payments.mollie.exceptions import MolliePaymentError

        refund_payload = '{"resource":"refund","id":"re_k_1","payment_id":"tr_k_1","amount":{"value":"1.00"}}'
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
            "refund": (
                lambda exc: patch(
                    self.SVC,
                    return_value=types.SimpleNamespace(
                        process_reversal_webhook=lambda **kw: (_ for _ in ()).throw(exc)
                    ),
                ),
                unified_payment_api.handle_refund_webhook,
                refund_payload,
            ),
            "chargeback": (
                lambda exc: patch(
                    self.SVC,
                    return_value=types.SimpleNamespace(
                        process_chargeback_webhook=lambda *a, **kw: (_ for _ in ()).throw(exc)
                    ),
                ),
                unified_payment_api.handle_chargeback_webhook,
                '{"id":"tr_k_1","status":"charged_back"}',
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

    def test_a_refund_and_a_chargeback_refusal_in_one_hour_each_get_a_row(self):
        """The id-less refusals share no id, so the dedupe key must still tell the endpoints
        apart: an anonymous refund refusal must not silence the chargeback one."""
        self.expectErrorLog("Mollie", "Webhook")
        before = self._processing_error_rows()
        for handler, payload in (
            (unified_payment_api.handle_refund_webhook, '{"resource":"refund"}'),
            (unified_payment_api.handle_chargeback_webhook, '{"status":"charged_back"}'),
        ):
            with install_fake_request(payload), patch(AUTH_PATH):
                frappe.local.response = frappe._dict()
                handler()
        self.assertEqual(self._processing_error_rows(), before + 2)

    def test_two_long_ids_sharing_a_prefix_are_not_one_failure(self):
        """Control for the dedupe key: it hashes the WHOLE id. Cutting the id to the logged
        length before hashing would fold these two into a single row."""
        prefix = "tr_" + "p" * 100
        self.expectErrorLog("Mollie", "Webhook")
        before = self._processing_error_rows()
        self._fail(prefix + "a" * 400)
        self._fail(prefix + "b" * 400)
        self.assertEqual(self._processing_error_rows(), before + 2)
