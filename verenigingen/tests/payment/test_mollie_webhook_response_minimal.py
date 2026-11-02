"""
The anonymous Mollie webhook answers with an acknowledgement and nothing else (#1781).

Mollie posts a bare ``id=tr_...`` with no credentials, so ANY caller who holds a payment
id (they appear in redirect URLs and e-mails) is, to the endpoint, Mollie. The endpoint
used to hand the processing result straight back: member id, Bank Transaction name,
amount and the member's Sales Invoices. Mollie only needs the status code (2xx stops the
retries), so the body carries ``{"status": "ok"}`` / ``{"status": "error"}`` and the
detail goes to the Error Log.

What is deliberately NOT equalised: the HTTP status of an id Mollie does not know (503
with Retry-After, because the idempotency check cannot tell a Mollie 404 from an outage)
versus one it does (2xx). Making both 2xx would silence the retry for a genuine outage;
that residual is tracked in its own issue.

Fixture shortcut, stated: ``Member.mollie_subscription_id`` / ``mollie_customer_id`` are
set with ``db.set_value`` (as in the sibling class this extends), standing in for a
completed subscription set-up. Only the Mollie fetch is stubbed.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.payment import test_provider_webhook_urls_guest_reachable as guest_reachable
from verenigingen.verenigingen_payments.mollie.exceptions import MolliePaymentError
from verenigingen.verenigingen_payments.mollie.services.payment_type_router import PaymentTypeRouter

PAYMENT_WEBHOOK = (
    "verenigingen.verenigingen_payments.mollie.api.webhooks.mollie_payment_webhook"
)
SERVICE = (
    "verenigingen.verenigingen_payments.mollie.api.unified_payment_api.get_unified_webhook_service"
)


class TestMollieWebhookBodyIsAnAcknowledgement(
    guest_reachable.TestSubscriptionWebhookBooksTheDuesPayment
):
    # The parent's one test is not repeated here (None is not collected by unittest).
    test_anonymous_subscription_notification_books_a_bank_transaction_for_the_member = None

    def _dues_payment(self, payment_id):
        paid = round(float(self.invoice_total) + 1.37, 2)
        return paid, SimpleNamespace(
            id=payment_id,
            status="paid",
            amount={
                "value": f"{paid:.2f}",
                "currency": frappe.get_value("Company", self.company, "default_currency"),
            },
            description="",
            subscription_id=self.subscription_id,
            customer_id=self.mollie_customer_id,
            paid_at="2025-04-10T09:00:00+00:00",
        )

    def _post(self, payment_id, fetch=None, fetch_error=None):
        """Guest dispatch; returns (body, http_status, new message_log rows, new Error Log rows)."""
        frappe.local.response.pop("http_status_code", None)
        before_msgs = len(frappe.local.message_log or [])
        before_errors = frappe.db.count("Error Log")
        stub = patch.object(PaymentTypeRouter, "fetch_payment", return_value=fetch, side_effect=fetch_error)
        with stub, patch.dict(frappe.conf, {"allow_mollie_test_mode": 1}):
            body = self._post_as_guest(PAYMENT_WEBHOOK, payment_id)
        status = frappe.local.response.get("http_status_code", 200)
        return (
            body,
            status,
            len(frappe.local.message_log or []) - before_msgs,
            frappe.db.count("Error Log") - before_errors,
        )

    def test_a_real_dues_payment_id_gets_only_an_ack_and_is_still_booked(self):
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        paid, payment = self._dues_payment(payment_id)

        body, status, new_msgs, new_errors = self._post(payment_id, fetch=payment)

        # Control: the booking really happened, so "ok" is not an error swallowed into a 200.
        booked = frappe.get_all("Bank Transaction", filters={"reference_number": payment_id}, pluck="name")
        self.assertEqual(len(booked), 1, body)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok"})
        wire = json.dumps(body, default=str)
        for secret in (self.member.name, booked[0], self.invoice_name, f"{paid:.2f}", str(paid)):
            self.assertNotIn(secret, wire)
        self.assertEqual(new_msgs, 0)
        self.assertEqual(new_errors, 0)

    def test_an_unknown_id_has_the_same_shape_and_channels_as_a_real_one(self):
        real_id = f"tr_{frappe.generate_hash(length=10)}"
        _paid, payment = self._dues_payment(real_id)
        real = self._post(real_id, fetch=payment)

        unknown_id = f"tr_{frappe.generate_hash(length=10)}"
        self.expectErrorLog("Mollie", "Webhook")
        unknown = self._post(unknown_id, fetch_error=MolliePaymentError("404 not found"))

        real_body, real_status, real_msgs, real_errors = real
        unknown_body, unknown_status, unknown_msgs, unknown_errors = unknown
        # Same keys, no echo of the id the caller sent, nothing on message_log / Error Log.
        self.assertEqual(set(unknown_body), set(real_body))
        self.assertNotIn(unknown_id, json.dumps(unknown_body, default=str))
        self.assertEqual(unknown_msgs, real_msgs)
        # Error Log is operator-side, not a caller channel: the failed lookup leaves one row
        # (an outage must be visible), the booked one none.
        self.assertEqual((real_errors, unknown_errors), (0, 1))
        # Documented residual (module docstring): a failure keeps its non-2xx status.
        self.assertGreaterEqual(unknown_status, 400, "a failed lookup must stay retryable")

    def test_a_processing_error_stays_non_2xx_but_its_detail_goes_to_the_error_log(self):
        secret = f"member {self.member.name} cannot be booked {frappe.generate_hash(length=6)}"
        fake = SimpleNamespace(
            process_payment_webhook=lambda pid, data: {
                "status": "error",
                "message": secret,
                "member": self.member.name,
            }
        )
        self.expectErrorLog("Mollie", "Webhook")
        with patch(SERVICE, return_value=fake), patch.dict(frappe.conf, {"allow_mollie_test_mode": 1}):
            frappe.local.response.pop("http_status_code", None)
            body = self._post_as_guest(PAYMENT_WEBHOOK, f"tr_{frappe.generate_hash(length=10)}")

        self.assertEqual(frappe.local.response.get("http_status_code"), 500)
        self.assertEqual(body, {"status": "error"})
        logged = frappe.get_all(
            "Error Log", filters={"error": ["like", f"%{secret}%"]}, pluck="name", limit=1
        )
        self.assertTrue(logged, "the detail the caller no longer sees must reach the Error Log")

    def test_an_unexpected_exception_does_not_echo_its_text(self):
        secret = f"boom {self.member.name}"

        def explode(pid, data):
            raise RuntimeError(secret)

        self.expectErrorLog("Mollie", "Webhook")
        with patch(SERVICE, return_value=SimpleNamespace(process_payment_webhook=explode)), patch.dict(
            frappe.conf, {"allow_mollie_test_mode": 1}
        ):
            frappe.local.response.pop("http_status_code", None)
            body = self._post_as_guest(PAYMENT_WEBHOOK, f"tr_{frappe.generate_hash(length=10)}")

        self.assertEqual(frappe.local.response.get("http_status_code"), 500)
        self.assertEqual(body, {"status": "error"})
        self.assertNotIn(secret, json.dumps(body))

    def test_the_wrapper_endpoints_do_not_echo_exception_text(self):
        """handle_mollie_payment_webhook / handle_unified_webhook put ``str(e)`` in the body."""
        from verenigingen.verenigingen_payments.mollie import exceptions

        secret = f"wrapper secret {self.member.name}"
        self.expectErrorLog("Mollie", "Webhook")
        base = "verenigingen.verenigingen_payments.mollie.api.webhooks."
        inner = "verenigingen.verenigingen_payments.mollie.api.unified_payment_api.handle_payment_webhook"
        for endpoint in ("handle_mollie_payment_webhook", "handle_unified_webhook"):
            for exc in (
                RuntimeError(secret),
                exceptions.MollieSecurityError(secret),
                exceptions.MollieWebhookError(secret),
            ):
                with self.subTest(endpoint=endpoint, exc=type(exc).__name__):
                    # Mock justified: the inner handler is the boundary being made to fail.
                    with patch(inner, side_effect=exc):
                        frappe.local.response.pop("http_status_code", None)
                        body = self._post_as_guest(base + endpoint, f"tr_{frappe.generate_hash(length=10)}")
                    self.assertNotIn(secret, json.dumps(body, default=str))
                    self.assertEqual(body, {"status": "error"})
                    self.assertGreaterEqual(frappe.local.response.get("http_status_code"), 400)

    def _post_json_as_guest(self, dotted, payload):
        from frappe.handler import execute_cmd
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request

        environ = EnvironBuilder(
            method="POST",
            path="/",
            data=json.dumps(payload),
            content_type="application/json",
            environ_overrides={"REMOTE_ADDR": self._unique_remote_addr()},
        ).get_environ()
        old = (getattr(frappe.local, "request", None), frappe.local.form_dict, frappe.session.user)
        self.addCleanup(self._restore_guest_dispatch_state, old)
        frappe.local.request = Request(environ)
        frappe.local.request.get_data(as_text=True)
        frappe.set_user("Guest")
        frappe.local.form_dict = frappe._dict()
        frappe.local.response.pop("http_status_code", None)
        # Mock justified: signature verification is an auth boundary with its own tests; this
        # test is about what the body says AFTER a caller got through it.
        with patch(
            "verenigingen.verenigingen_payments.mollie.utils.webhook_security.authenticate_mollie_webhook"
        ):
            return execute_cmd(dotted)

    def test_refund_and_chargeback_endpoints_answer_with_an_ack_only(self):
        api = "verenigingen.verenigingen_payments.mollie.api.unified_payment_api."
        service = (
            "verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified."
            "UnifiedWebhookWrapperService"
        )
        booked = {"status": "success", "member": self.member.name, "amount": 12.5, "payment_entry": "PE-1"}
        failed = {"status": "error", "message": f"cannot book for {self.member.name}"}
        cases = (
            ("handle_refund_webhook", "process_reversal_webhook", {"payment_id": "tr_x", "refund": {"id": "re_x"}}),
            ("handle_chargeback_webhook", "process_chargeback_webhook", {"id": "tr_x"}),
        )
        for endpoint, method, payload in cases:
            for result, expected_status, expected_body in ((booked, 200, "ok"), (failed, 500, "error")):
                with self.subTest(endpoint=endpoint, outcome=expected_body):
                    # Mock justified: the booking service is the boundary; it is given the
                    # two outcomes (booked / could not book) the endpoint must shape.
                    self.expectErrorLog("Mollie", "Webhook")
                    with patch(f"{service}.{method}", return_value=dict(result)):
                        body = self._post_json_as_guest(api + endpoint, payload)
                    self.assertEqual(body, {"status": expected_body})
                    self.assertEqual(frappe.local.response.get("http_status_code") or 200, expected_status)
