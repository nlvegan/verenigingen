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

import base64
import hashlib
import hmac
import json
import time
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
        self.addCleanup(setattr, frappe.local, "response", getattr(frappe.local, "response", None))
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


class TestPontoWebhookEnabledFlagIsNotAnOracle(_GuestWebhookCase):
    """#1813: ``enable_webhooks`` is honoured only AFTER the request is authenticated, so
    an anonymous caller cannot read whether Ponto webhooks are on from the status code.

    Every unauthenticated shape is posted with webhooks on and off and compared on every
    caller-visible channel (body, HTTP status, message_log) plus the Error Log rows it
    writes. Probe shortcut: the two settings are written with ``set_single_value``.
    """

    def setUp(self):
        super().setUp()
        for field in ("enable_webhooks", "require_webhook_signature"):
            old = frappe.db.get_single_value("Ponto Settings", field)
            self.addCleanup(frappe.db.set_single_value, "Ponto Settings", field, old)
        frappe.db.set_single_value("Ponto Settings", "require_webhook_signature", 1)

    def _enable(self, flag):
        frappe.db.set_single_value("Ponto Settings", "enable_webhooks", flag)

    def _event(self):
        return {"data": {"id": f"evt-{uuid.uuid4().hex[:8]}", "type": "pontoConnect.nope", "attributes": {}}}

    def _observe(self, flag, *, headers=None, verify=None, event=None):
        """(body, status, message_log, error-log rows written) for one anonymous POST."""
        self._enable(flag)
        # Error rows are written once per hour per IP (log_error_once): reset that window so
        # the on and off observations are not skewed by whichever ran first.
        frappe.cache.delete_keys("webhook_error_log_once:*")
        before = frappe.db.count("Error Log")
        with patch(f"{PONTO}.verify_ponto_webhook", **verify or {"return_value": {"sub": "x"}}):  # Mock justified: JWKS fetch
            body, status, messages = self._post(
                f"{PONTO}.handle_ponto_webhook",
                event or self._event(),
                headers=headers or {},
                ip="203.0.113.50",
            )
        return body, status, messages, frappe.db.count("Error Log") - before

    def _bad_signature(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoWebhookError

        return {"side_effect": PontoWebhookError("bad signature")}

    def test_bad_signature_is_refused_identically_with_webhooks_on_and_off(self):
        bad = self._bad_signature()
        on = self._observe(1, headers={"Signature": "forged"}, verify=bad)
        off = self._observe(0, headers={"Signature": "forged"}, verify=bad)
        self.assertEqual(on[:2], ({"status": "error"}, 401), "control: the refusal is real")
        self.assertEqual(on, off)

    def test_missing_signature_is_refused_identically_with_webhooks_on_and_off(self):
        on = self._observe(1)
        off = self._observe(0)
        self.assertEqual(on[:2], ({"status": "error"}, 401), "control: the refusal is real")
        self.assertEqual(on, off)

    # A signed delivery with no recognisable event type: processing it answers 400 ("Unknown
    # event format"), so a 200 ack means the handler did NOT process it. Guest cannot insert
    # the Webhook Processing Log, so that row is not an observable.
    _NO_EVENT = {"data": {"id": "evt-no-type"}}

    def test_a_valid_signature_with_webhooks_off_is_acked_and_processes_nothing(self):
        """The disabled integration still acks a genuine Ponto delivery (no retry storm)
        but does not process it."""
        body, status, _, _ = self._observe(0, headers={"Signature": "jwt"}, event=self._NO_EVENT)
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_a_valid_signature_with_webhooks_on_is_still_processed(self):
        """Control for the test above: the same delivery with webhooks on IS processed
        (and refused as an unknown event format), so the off-ack means something."""
        body, status, _, _ = self._observe(1, headers={"Signature": "jwt"}, event=self._NO_EVENT)
        self.assertEqual((status, body), (400, {"status": "error"}))


class _PontoJwtCase(_GuestWebhookCase):
    """Real RS512 JWT, real verification and real dispatch; only the JWKS fetch is stubbed.

    Probe shortcut, stated per the brief: the settings switches are written with
    ``set_single_value`` and restored on cleanup.
    """

    def setUp(self):
        super().setUp()
        from verenigingen.tests.sepa.test_ponto_webhook_security_unit import _build_jwk, _generate_keypair

        for field, value in (
            ("enable_webhooks", 1),
            ("require_webhook_signature", 1),
            ("webhook_application_id", f"expected-{uuid.uuid4().hex[:10]}"),
        ):
            old = frappe.db.get_single_value("Ponto Settings", field)
            frappe.db.set_single_value("Ponto Settings", field, value)
            self.addCleanup(frappe.db.set_single_value, "Ponto Settings", field, old)
        self.expected = frappe.db.get_single_value("Ponto Settings", "webhook_application_id")
        # MyISAM Error Log: nothing rolls back, so delete the rows this test wrote. Scoped by
        # creation time (no whole-table read), and only to rows the verifier's handler writes.
        self._log_start = frappe.utils.now()
        self.addCleanup(self._delete_new_ponto_error_logs)
        self.private_pem, public_key = _generate_keypair()
        signing_key, _ = _build_jwk(public_key)
        patcher = patch(
            "verenigingen.verenigingen_payments.ponto.utils.webhook_security.PontoWebhookVerifier._fetch_signing_key",
            return_value=signing_key,
        )  # Mock justified: JWKS HTTP fetch
        patcher.start()
        self.addCleanup(patcher.stop)

    def _deliver(self, audience=None, issuer=None, token_builder=None, **token_kwargs):
        from verenigingen.tests.sepa.test_ponto_webhook_security_unit import TEST_ISSUER, _make_token

        raw = json.dumps(
            {"data": {"id": f"evt-{uuid.uuid4().hex[:8]}", "type": "pontoConnect.nope", "attributes": {}}}
        ).encode()
        if token_builder:
            token = token_builder(raw)
        else:
            token = _make_token(
                self.private_pem,
                raw,
                audience=audience if audience is not None else self.expected,
                issuer=issuer or TEST_ISSUER,
                **token_kwargs,
            )
        self.last_token = token
        # unique per delivery: log_error_once dedupes per IP per hour, so a prior row could hide ours
        ip = f"2001:db8::{uuid.uuid4().hex[:4]}"
        return self._post(f"{PONTO}.handle_ponto_webhook", raw=raw, headers={"Signature": token}, ip=ip)

    def _new_ponto_error_rows(self):
        return frappe.get_all(
            "Error Log",
            filters={"creation": [">=", self._log_start], "method": ["like", "Ponto Error%"]},
            fields=["name", "method", "error"],
        )

    def _delete_new_ponto_error_logs(self):
        names = [r.name for r in self._new_ponto_error_rows()]
        if names:
            frappe.db.delete("Error Log", {"name": ["in", names]})

    def _assert_no_time_or_alg_diagnostics(self):
        """The new fields belong to the expired / immature / wrong-alg refusals ONLY."""
        for row in self._new_ponto_error_rows():
            for field in ("server_time", "received_algorithm"):
                self.assertNotIn(field, row.error, f"{field} leaked into an unrelated refusal row")

    def _assert_token_not_leaked(self, body, messages):
        """A signed token is replayable until it expires; it must reach neither the Error Log nor the caller."""
        self.assertTrue(self.last_token)
        for text in self._error_log_texts():
            self.assertNotIn(self.last_token, text, "the raw webhook token must not be written to the Error Log")
        self.assertNotIn(self.last_token, json.dumps(body) + " ".join(messages))


class TestPontoWebhookAudienceDiagnostics(_PontoJwtCase):
    """#2172: a refused audience must leave BOTH the expected and the received value in the Error Log."""

    def _audience_rows(self):
        return [t for t in self._error_log_texts() if "Invalid webhook audience" in t]

    def test_mismatched_audience_is_refused_and_both_values_are_logged(self):
        received = f"received-{uuid.uuid4().hex[:10]}"
        body, status, messages = self._deliver(received)
        self.assertEqual((status, body), (401, {"status": "error"}))
        rows = [t for t in self._audience_rows() if received in t]
        self.assertEqual(len(rows), 1, "the refusal must write one Error Log row naming the received aud")
        self.assertIn(self.expected, rows[0])
        self.assertNotIn(received, " ".join(messages), "the received aud must not reach the caller")
        self._assert_token_not_leaked(body, messages)
        self._assert_no_time_or_alg_diagnostics()

    def test_list_audience_is_logged_and_still_refused(self):
        received = [f"one-{uuid.uuid4().hex[:8]}", f"two-{uuid.uuid4().hex[:8]}"]
        _, status, _ = self._deliver(received)
        self.assertEqual(status, 401)
        rows = [t for t in self._audience_rows() if received[0] in t]
        self.assertEqual(len(rows), 1)
        self.assertIn(received[1], rows[0])

    def test_received_claim_is_safe_for_every_shape_a_token_can_carry(self):
        import jwt

        from verenigingen.verenigingen_payments.ponto.utils.webhook_security import received_claim

        def token(**claims):
            return jwt.encode(claims, self.private_pem, algorithm="RS512")

        self.assertIsNone(received_claim("not-a-jwt", "aud"))
        self.assertIsNone(received_claim(None, "aud"))
        self.assertIsNone(received_claim(token(iss="x"), "aud"))
        self.assertEqual(received_claim(token(aud="a-b"), "aud"), "a-b")
        self.assertEqual(received_claim(token(aud=["a", "b"]), "aud"), ["a", "b"])
        self.assertEqual(len(received_claim(token(aud="x" * 500), "aud")), 200)
        self.assertEqual(len(received_claim(token(aud=[f"v{i}" for i in range(7)]), "aud")), 5)
        # shapes PyJWT reports as InvalidAudienceError ("Invalid claim format") reach this in production
        for odd in (5, {"k": "v"}, [["nested"]]):
            self.assertIsInstance(received_claim(token(aud=odd), "aud"), (str, list))

    def test_list_audience_is_logged_as_elements_not_as_a_python_repr(self):
        received = [f"one-{uuid.uuid4().hex[:8]}", f"two-{uuid.uuid4().hex[:8]}"]
        self._deliver(received)
        row = [t for t in self._audience_rows() if received[0] in t][0]
        self.assertIn(received[1], row)
        # a real list renders as ['a', 'b']; a stringified one would be wrapped in quotes
        self.assertIn(f"'received_audience': ['{received[0]}'", row)

    def test_mismatched_issuer_is_refused_and_both_values_are_logged(self):
        received = f"https://evil-{uuid.uuid4().hex[:8]}.example"
        body, status, messages = self._deliver(self.expected, issuer=received)
        self.assertEqual(status, 401)
        self._assert_token_not_leaked(body, messages)
        self._assert_no_time_or_alg_diagnostics()
        rows = [t for t in self._error_log_texts() if "Invalid webhook issuer" in t and received in t]
        self.assertEqual(len(rows), 1)
        self.assertIn("expected_issuer", rows[0])


class TestPontoWebhookTimeAndAlgorithmDiagnostics(_PontoJwtCase):
    """#2324: an expired / not-yet-valid token must log exp, iat and the server clock; a wrong
    algorithm must log the header's alg. A clock skew and a replayed delivery look the same
    without them. The caller's answer must not change (status, body, message_log, response dict).
    """

    def _assert_unchanged_refusal(self, body, status, messages):
        self.assertEqual((status, body), (401, {"status": "error"}))
        self.assertEqual(messages, [])
        # the whole response dict (status code + headers), not just the pieces named above
        response = dict(frappe.local.response)
        headers = {
            k: v for k, v in response.pop("headers").items() if k not in ("X-RateLimit-Remaining", "X-RateLimit-Reset")
        }  # the two counters move with every request
        self.assertEqual(response, {"http_status_code": 401})
        self.assertEqual(
            headers,
            {
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Window": "3600",
            },
        )
        self._assert_token_not_leaked(body, messages)

    def _server_time_in(self, row, before, after):
        import re

        found = re.search(r"'server_time': (\d+)", row)
        self.assertTrue(found, f"no server_time in: {row}")
        self.assertTrue(before <= int(found.group(1)) <= after)

    def test_expired_token_logs_exp_iat_and_server_time(self):
        now = int(time.time())
        iat = now - 1000 - uuid.uuid4().int % 500  # unique per run, so the row is ours
        body, status, messages = self._deliver(iat=iat, exp_offset=300)
        self._assert_unchanged_refusal(body, status, messages)
        rows = [t for t in self._error_log_texts() if "Webhook signature expired" in t and str(iat) in t]
        self.assertEqual(len(rows), 1)
        self.assertIn(f"'exp': '{iat + 300}'", rows[0])
        self.assertIn(f"'iat': '{iat}'", rows[0])
        self._server_time_in(rows[0], now, int(time.time()))

    def test_not_yet_valid_token_logs_exp_iat_and_server_time(self):
        now = int(time.time())
        iat = now + 1000 + uuid.uuid4().int % 500  # in the future, beyond the 30s leeway
        body, status, messages = self._deliver(iat=iat, exp_offset=300)
        self._assert_unchanged_refusal(body, status, messages)
        rows = [t for t in self._error_log_texts() if str(iat) in t and "'server_time'" in t]
        self.assertEqual(len(rows), 1, "the immature refusal must write one row naming iat and the server clock")
        self.assertIn(f"'exp': '{iat + 300}'", rows[0])
        self._server_time_in(rows[0], now, int(time.time()))

    def test_nbf_immature_token_logs_nbf(self):
        nbf = int(time.time()) + 2000 + uuid.uuid4().int % 500
        body, status, messages = self._deliver(extra_claims={"nbf": nbf})
        self._assert_unchanged_refusal(body, status, messages)
        rows = [t for t in self._error_log_texts() if "Webhook signature not yet valid" in t and str(nbf) in t]
        self.assertEqual(len(rows), 1, "an nbf-immature token must name its nbf")
        self.assertIn(f"'nbf': '{nbf}'", rows[0])

    def test_wrong_algorithm_logs_the_header_alg(self):
        import jwt

        def hs256(raw):
            claims = {"iss": "x", "aud": self.expected, "iat": int(time.time()), "exp": int(time.time()) + 300}
            return jwt.encode(claims, "k" * 64, algorithm="HS256", headers={"kid": "whatever"})

        body, status, messages = self._deliver(token_builder=hs256)
        self._assert_unchanged_refusal(body, status, messages)
        rows = [t for t in self._error_log_texts() if "Invalid webhook signature algorithm" in t]
        self.assertEqual(len(rows), 1)
        self.assertIn("'received_algorithm': 'HS256'", rows[0])
        self.assertIn("RS512", rows[0])

    def test_hostile_header_values_are_capped_and_never_raise(self):
        import jwt

        from verenigingen.verenigingen_payments.ponto.utils.webhook_security import (
            received_header_alg,
            token_time_diagnostics,
        )

        def forge(header, claims=None):
            enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
            return f"{enc(header)}.{enc(claims or {})}.sig"

        self.assertEqual(len(received_header_alg(forge({"alg": "A" * 500}))), 50)
        self.assertEqual(received_header_alg(forge({"alg": 5})), "5")
        hostile = received_header_alg(forge({"alg": "HS\n\x00[SECRET]\r\u2028x"}))
        self.assertTrue(all(32 <= ord(c) < 127 for c in hostile), repr(hostile))
        self.assertTrue(hostile.startswith("HS") and "[SECRET]" in hostile)
        self.assertIsNone(received_header_alg(forge({"typ": "JWT"})))
        self.assertEqual(
            token_time_diagnostics(forge({"alg": "RS512"}, {"exp": "9" * 500, "iat": [1, 2]}))["exp"],
            "9" * 200,
        )
        # control: the readable case does return values, so the Nones below mean "unreadable"
        good = jwt.encode({"exp": 7, "iat": 5}, self.private_pem, algorithm="RS512")
        self.assertEqual(received_header_alg(good), "RS512")
        self.assertEqual(token_time_diagnostics(good)["iat"], "5")
        for garbage in ("not-a-jwt", "", None, 12, b"\xff\xfe", "a.b.c", "...."):
            self.assertIsNone(received_header_alg(garbage))
            diag = token_time_diagnostics(garbage)
            self.assertEqual((diag["exp"], diag["iat"]), (None, None))
            self.assertIsInstance(diag["server_time"], int)

    def test_unreadable_claims_with_a_readable_header_yield_no_times(self):
        from verenigingen.verenigingen_payments.ponto.utils.webhook_security import (
            received_header_alg,
            token_time_diagnostics,
        )

        header = base64.urlsafe_b64encode(json.dumps({"alg": "x"}).encode()).decode()
        claims = base64.urlsafe_b64encode(b"[1]").decode()
        token = f"{header}.{claims}.sig"
        self.assertEqual(received_header_alg(token), "x")
        self.assertEqual(token_time_diagnostics(token)["exp"], None)

    def test_malformed_token_is_still_refused_without_the_new_fields(self):
        body, status, messages = self._deliver(token_builder=lambda raw: "not-a-jwt")
        self._assert_unchanged_refusal(body, status, messages)
        self._assert_no_time_or_alg_diagnostics()

    def test_bad_signature_is_refused_without_the_new_fields(self):
        import jwt

        from verenigingen.tests.sepa.test_ponto_webhook_security_unit import _generate_keypair

        other_pem, _ = _generate_keypair()

        def forged(raw):
            claims = {"iss": "x", "aud": self.expected, "iat": int(time.time()), "exp": int(time.time()) + 300}
            return jwt.encode(claims, other_pem, algorithm="RS512", headers={"kid": "k"})

        body, status, messages = self._deliver(token_builder=forged)
        self._assert_unchanged_refusal(body, status, messages)
        self._assert_no_time_or_alg_diagnostics()

    def test_a_valid_token_writes_no_ponto_error_row(self):
        """Control for every test above: a diagnostic logged on EVERY request would also pass
        them. A verified delivery must leave no Ponto Error row at all."""
        self._deliver()
        self.assertEqual([r.error[:200] for r in self._new_ponto_error_rows()], [])
