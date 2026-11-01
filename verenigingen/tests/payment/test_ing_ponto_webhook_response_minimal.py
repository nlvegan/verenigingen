"""
The anonymous ING Checkout and Ponto webhooks answer with an ack, not the processing
result (#1804), and a refusal does not tell the caller whether the ING webhook secret is
configured (#1772).

Everything goes through Frappe's real dispatch (``execute_cmd``) as Guest with a real
werkzeug Request and a real HMAC, so ``frappe.local.message_log`` is what the framework
would serialise into ``_server_messages``. Only the two external boundaries are stubbed:
the Pay.nl IP-list fetch and the Ponto JWKS verification.

Probe shortcut, stated per the brief: the Ponto "enabled / signature required" switches
and the ING secret are written directly (``set_single_value`` / ``set_encrypted_password``)
rather than through the settings forms, and restored on cleanup.
"""

import hashlib
import hmac
import json
import uuid
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils.password import remove_encrypted_password, set_encrypted_password
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ING = "verenigingen.verenigingen_payments.ing_checkout.api.webhook"
PONTO = "verenigingen.verenigingen_payments.ponto.api.webhook"
SEC = "verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security"
SETTINGS = "Verenigingen Payments Settings"
SECRET_FIELD = "ing_checkout_webhook_secret"
PAYNL_IP = "198.51.100.7"
DETAIL = "internal-detail-must-not-reach-the-caller"


class _GuestWebhookCase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # The handlers log every refusal/failure to the Error Log by design; that is the
        # operator's channel and part of what these tests assert.
        self.expectErrorLog("Ing_Checkout", "Ponto Error", "ING Checkout webhook rejected")

    def _post(self, dotted, payload=None, *, raw=None, headers=None, ip=None):
        """Dispatch as Guest. Returns (body, http_status, message_log_texts)."""
        from frappe.handler import execute_cmd

        body = raw if raw is not None else json.dumps(payload).encode()
        environ = EnvironBuilder(
            method="POST",
            path="/",
            data=body,
            content_type="application/json",
            headers=headers or {},
            environ_overrides={"REMOTE_ADDR": ip or f"203.0.113.{uuid.uuid4().int % 200 + 1}"},
        ).get_environ()
        old = (getattr(frappe.local, "request", None), frappe.local.form_dict, frappe.session.user)
        self.addCleanup(self._undo_guest_post, old)
        frappe.local.request = Request(environ)
        frappe.local.request.get_data()
        frappe.set_user("Guest")  # resets form_dict, so first
        frappe.local.form_dict = frappe._dict()
        frappe.local.response = frappe._dict()
        frappe.local.message_log = []
        result = execute_cmd(dotted)
        status = frappe.local.response.get("http_status_code") or 200
        return result, status, [str(m) for m in frappe.local.message_log]

    @staticmethod
    def _undo_guest_post(old):
        frappe.local.request, frappe.local.form_dict = old[0], old[1]
        frappe.set_user(old[2])

    def _error_log_texts(self):
        return [
            f"{r.method}\n{r.error}"
            for r in frappe.get_all("Error Log", fields=["method", "error"], order_by="creation desc", limit=40)
        ]

    def _set_ing_secret(self, secret):
        if secret is None:
            remove_encrypted_password(SETTINGS, SETTINGS, SECRET_FIELD)
        else:
            set_encrypted_password(SETTINGS, SETTINGS, secret, SECRET_FIELD)

    def _hmac_for_json(self, payload, secret):
        raw = json.dumps(payload).encode()
        return raw, hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class TestIngWebhookAck(_GuestWebhookCase):
    def setUp(self):
        super().setUp()
        self.secret = "s3cret-" + frappe.generate_hash(length=8)
        self._set_ing_secret(self.secret)
        self.addCleanup(self._set_ing_secret, None)
        patcher = patch(f"{SEC}.fetch_paynl_ip_addresses", return_value=[PAYNL_IP])  # Mock justified: Pay.nl HTTP
        patcher.start()
        self.addCleanup(patcher.stop)

    def _signed(self, dotted, payload):
        raw, sig = self._hmac_for_json(payload, self.secret)
        return self._post(dotted, raw=raw, headers={"X-Pay-Signature": sig})

    def _ing_order_payload(self, order_id):
        return {"id": order_id, "object": {"reference": "nope", "amount": {"value": 2500}}}

    def test_accepted_payment_is_acked_without_the_result(self):
        order_id = f"EX-{frappe.generate_hash(length=8)}"
        body, status, messages = self._signed(f"{ING}.handle_payment", self._ing_order_payload(order_id))
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok"})
        # control: the processing really ran, so the ack hides something that existed
        self.assertTrue(frappe.db.exists("ING Checkout Transaction", {"transaction_id": order_id}))
        self.assertEqual(messages, [])

    def test_accepted_mandate_is_acked_without_the_result(self):
        body, status, _ = self._signed(f"{ING}.handle_mandate", self._ing_order_payload(f"MD-{frappe.generate_hash(length=8)}"))
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_accepted_direct_debit_is_acked_known_and_unknown_alike(self):
        from verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction import (
            get_or_create_transaction,
        )

        known = f"DD-{frappe.generate_hash(length=8)}"
        get_or_create_transaction(transaction_id=known, amount=1)
        unknown = f"DD-{frappe.generate_hash(length=8)}"
        a = self._signed(f"{ING}.handle_direct_debit", self._ing_order_payload(known))
        b = self._signed(f"{ING}.handle_direct_debit", self._ing_order_payload(unknown))
        self.assertEqual(a, b)
        self.assertEqual(a[:2], ({"status": "ok"}, 200))

    def test_processing_failure_keeps_500_and_hides_the_exception(self):
        # A REAL processing failure (a non-numeric amount makes Decimal raise inside
        # _process_payment_webhook), not an injected one.
        payload = self._ing_order_payload("EX-FAIL-1")
        payload["object"]["amount"]["value"] = "not-a-number"
        errors_before = frappe.db.count("Error Log")
        body, status, messages = self._signed(f"{ING}.handle_payment", payload)
        self.assertEqual((status, body), (500, {"status": "error"}))
        self.assertEqual(messages, [])
        self.assertGreater(frappe.db.count("Error Log"), errors_before, "detail must reach the Error Log")

    def test_business_error_keeps_400_and_hides_the_exception(self):
        err = frappe.get_module(ING).INGCheckoutWebhookError(DETAIL)
        limiter = MagicMock()
        limiter.check_rate_limit.side_effect = err
        with patch(f"{ING}.get_webhook_rate_limiter", return_value=limiter):  # Mock justified: boundary raising
            body, status, messages = self._signed(f"{ING}.handle_payment", self._ing_order_payload("EX-FAIL-2"))
        self.assertEqual((status, body), (400, {"status": "error"}))
        self.assertNotIn(DETAIL, " ".join(messages))

    def test_invalid_json_does_not_echo_the_parser_message(self):
        raw = b"not-json{"
        sig = hmac.new(self.secret.encode(), raw, hashlib.sha256).hexdigest()
        body, status, _ = self._post(f"{ING}.handle_payment", raw=raw, headers={"X-Pay-Signature": sig})
        self.assertEqual((status, body), (400, {"status": "error"}))

    def test_rate_limit_keeps_429_and_hides_the_reason(self):
        limiter = MagicMock()
        limiter.check_rate_limit.return_value = (False, DETAIL)
        with patch(f"{ING}.get_webhook_rate_limiter", return_value=limiter):  # Mock justified: limiter boundary
            body, status, messages = self._signed(f"{ING}.handle_payment", self._ing_order_payload("EX-RL"))
        self.assertEqual((status, body), (429, {"status": "rate_limited"}))
        self.assertNotIn(DETAIL, " ".join(messages))

    def test_duplicate_is_acked_like_a_fresh_delivery(self):
        with patch(f"{ING}.is_duplicate_webhook", return_value=True):  # Mock justified: dedup store
            body, status, _ = self._signed(f"{ING}.handle_payment", self._ing_order_payload("EX-DUP"))
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_refusals_are_indistinguishable_on_every_caller_visible_channel(self):
        """#1772: bad signature, no secret + unlisted IP, no secret + no signature."""
        payload = self._ing_order_payload("EX-REFUSE")
        raw = json.dumps(payload).encode()
        spoof = "192.0.2.99"  # not in the Pay.nl list

        bad_sig = self._post(
            f"{ING}.handle_payment", raw=raw, headers={"X-Pay-Signature": "00" * 32}, ip=spoof
        )
        self._set_ing_secret(None)
        no_secret_with_sig = self._post(
            f"{ING}.handle_payment", raw=raw, headers={"X-Pay-Signature": "00" * 32}, ip=spoof
        )
        no_secret_no_sig = self._post(f"{ING}.handle_payment", raw=raw, ip=spoof)

        self.assertEqual(bad_sig[1], 401)
        self.assertEqual(bad_sig, no_secret_with_sig)
        self.assertEqual(bad_sig, no_secret_no_sig)
        self.assertEqual(bad_sig[0], {"status": "error"})
        self.assertEqual(bad_sig[2], [], "refusal must not append to message_log")

    def test_the_secret_lookup_does_not_append_to_message_log_when_unset(self):
        self._set_ing_secret(None)
        frappe.local.message_log = []
        from verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security import get_webhook_secret

        self.assertIsNone(get_webhook_secret())
        self.assertEqual(frappe.local.message_log, [])

    def test_guest_log_insert_failure_does_not_reach_the_caller(self):
        """#1772 (2): the Guest insert of Webhook Processing Log is refused; that refusal
        must not travel in message_log. (Whether the row should persist is a separate
        question, see the PR body.)"""
        _, _, messages = self._signed(f"{ING}.handle_payment", self._ing_order_payload(f"EX-{frappe.generate_hash(length=8)}"))
        self.assertNotIn("Webhook Processing Log", " ".join(messages))


class TestPontoWebhookAck(_GuestWebhookCase):
    def setUp(self):
        super().setUp()
        for field, value in (("enable_webhooks", 1), ("require_webhook_signature", 1)):
            old = frappe.db.get_single_value("Ponto Settings", field)
            frappe.db.set_single_value("Ponto Settings", field, value)
            self.addCleanup(frappe.db.set_single_value, "Ponto Settings", field, old)
        patcher = patch(f"{PONTO}.verify_ponto_webhook", return_value={"sub": "x"})  # Mock justified: JWKS fetch
        patcher.start()
        self.addCleanup(patcher.stop)

    def _event(self, etype="pontoConnect.synchronization.succeededWithoutChange"):
        return {"data": {"id": f"evt-{uuid.uuid4().hex[:8]}", "type": etype, "attributes": {}}}

    def test_accepted_event_is_acked_without_the_result(self):
        body, status, messages = self._post(
            f"{PONTO}.handle_ponto_webhook", self._event(), headers={"Signature": "jwt"}
        )
        self.assertEqual((status, body), (200, {"status": "ok"}))
        self.assertEqual(messages, [])

    def test_unknown_event_type_is_acked_like_a_known_one(self):
        known = self._post(f"{PONTO}.handle_ponto_webhook", self._event(), headers={"Signature": "jwt"})
        unknown = self._post(
            f"{PONTO}.handle_ponto_webhook", self._event("pontoConnect.nope"), headers={"Signature": "jwt"}
        )
        self.assertEqual(known, unknown)

    def _post_with_raising_limiter(self, exc):
        limiter = MagicMock()
        limiter.check_rate_limit.side_effect = exc
        with patch(f"{PONTO}.get_webhook_rate_limiter", return_value=limiter):  # Mock justified: boundary raising
            return self._post(f"{PONTO}.handle_ponto_webhook", self._event(), headers={"Signature": "jwt"})

    def test_unexpected_failure_keeps_500_and_hides_the_exception(self):
        body, status, messages = self._post_with_raising_limiter(ValueError(DETAIL))
        self.assertEqual((status, body), (500, {"status": "error"}))
        self.assertNotIn(DETAIL, " ".join(messages))
        self.assertTrue(any(DETAIL in t for t in self._error_log_texts()), "detail must reach the Error Log")

    def test_business_error_keeps_400_and_hides_the_exception(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoWebhookError

        body, status, messages = self._post_with_raising_limiter(PontoWebhookError(DETAIL))
        self.assertEqual((status, body), (400, {"status": "error"}))
        self.assertNotIn(DETAIL, " ".join(messages))

    def test_missing_signature_keeps_401_and_does_not_name_the_setting(self):
        body, status, _ = self._post(f"{PONTO}.handle_ponto_webhook", self._event())
        self.assertEqual((status, body), (401, {"status": "error"}))

    def test_invalid_json_does_not_echo_the_parser_message(self):
        body, status, _ = self._post(
            f"{PONTO}.handle_ponto_webhook", raw=b"nope{", headers={"Signature": "jwt"}
        )
        self.assertEqual((status, body), (400, {"status": "error"}))

    def test_rate_limit_keeps_429_and_hides_the_reason(self):
        limiter = MagicMock()
        limiter.check_rate_limit.return_value = (False, DETAIL)
        with patch(f"{PONTO}.get_webhook_rate_limiter", return_value=limiter):  # Mock justified: limiter boundary
            body, status, _ = self._post(
                f"{PONTO}.handle_ponto_webhook", self._event(), headers={"Signature": "jwt"}
            )
        self.assertEqual((status, body), (429, {"status": "rate_limited"}))

    def test_disabled_webhooks_do_not_announce_it_in_the_body(self):
        frappe.db.set_single_value("Ponto Settings", "enable_webhooks", 0)
        body, status, _ = self._post(
            f"{PONTO}.handle_ponto_webhook", self._event(), headers={"Signature": "jwt"}
        )
        self.assertEqual((status, body), (200, {"status": "ok"}))
