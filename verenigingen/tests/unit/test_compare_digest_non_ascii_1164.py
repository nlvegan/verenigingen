"""#1164: hmac.compare_digest raises TypeError on a non-ASCII str.

A guest-supplied header/token such as ``héllo`` reached ``hmac.compare_digest`` at
eleven call sites and raised instead of being refused, so the caller saw a different
answer (raw exception text, a 500, an extra Error Log row) than for an ordinary wrong
token -- the same defect #1108/#1103 fixed in two helpers.

Real-flow tests (Zabbix receiver, Mollie webhook authentication) compare a wrong-ASCII
token with a non-ASCII token on every channel: return value, HTTP status code,
``message_log`` and Error Log rows. They are required to be refused IDENTICALLY.
The dead-code sites are exercised by calling the function directly (no production
caller exists, so there is no flow to drive).
"""

import hashlib
import hmac
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_payment_gateways_subscription_sweep import (
    WEBHOOK_SECRET,
    _json_event,
    _mollie_auth_config,
)
from verenigingen.verenigingen_payments.mollie.tests.fixtures.webhook_fixtures import (
    install_fake_request,
    sign_payload,
)
from verenigingen.verenigingen_payments.utils import payment_gateways as pg

_SCRIPTS_MONITORING = str(Path(__file__).resolve().parents[3] / "scripts" / "monitoring")
if _SCRIPTS_MONITORING not in sys.path:
    sys.path.insert(0, _SCRIPTS_MONITORING)

import zabbix_integration  # noqa: E402

NON_ASCII = "héllo"
WRONG_ASCII = "hallo"
ZABBIX_SECRET = "zabbix-secret-1164"
ZABBIX_TOKEN = "zabbix-token-1164"


@contextmanager
def _conf(**values):
    # Mock justified: execution-context assignment (frappe.conf) for site config keys
    # that production reads from site_config.json; restored in the finally.
    missing = object()
    previous = {k: frappe.conf.get(k, missing) for k in values}
    frappe.conf.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is missing:
                frappe.conf.pop(key, None)
            else:
                frappe.conf[key] = value


@contextmanager
def _real_request(headers, body=b"{}"):
    """Bind a real werkzeug Request, so headers go through werkzeug's own decoding."""
    prev = getattr(frappe.local, "request", None)
    environ = EnvironBuilder(method="POST", data=body, headers=headers).get_environ()
    frappe.local.request = Request(environ)
    try:
        yield
    finally:
        frappe.local.request = prev


def _error_log_count_1164():
    return frappe.db.count("Error Log")


class TestSafeCompareHelper(EnhancedTestCase):
    def test_matching_and_mismatching_ascii(self):
        from verenigingen.utils.security.constant_time import safe_compare_digest

        self.assertTrue(safe_compare_digest("abc123", "abc123"))
        self.assertFalse(safe_compare_digest("abc123", "abc124"))

    def test_non_ascii_is_refused_not_raised(self):
        from verenigingen.utils.security.constant_time import safe_compare_digest

        self.assertFalse(safe_compare_digest(NON_ASCII, "abc123"))
        self.assertFalse(safe_compare_digest("abc123", NON_ASCII))
        self.assertTrue(safe_compare_digest(NON_ASCII, NON_ASCII))

    def test_lone_surrogate_is_refused_not_raised(self):
        # A lone surrogate (e.g. from a JSON "\\ud800" escape) cannot be encoded
        # as strict UTF-8; it must still be an ordinary "not equal".
        from verenigingen.utils.security.constant_time import safe_compare_digest

        self.assertFalse(safe_compare_digest("\ud800", "x"))
        self.assertFalse(safe_compare_digest("x", "\ud800"))

    def test_distinct_non_ascii_values_do_not_collide(self):
        # Guards against a lossy encoding (ascii/replace) that maps every
        # non-ASCII character to "?" and so makes different values equal.
        from verenigingen.utils.security.constant_time import safe_compare_digest

        self.assertFalse(safe_compare_digest("\u00e9", "?"))
        self.assertFalse(safe_compare_digest("\u00e9", "\u00e8"))
        self.assertFalse(safe_compare_digest("\ud800", "?"))

    def test_none_is_refused(self):
        from verenigingen.utils.security.constant_time import safe_compare_digest

        self.assertFalse(safe_compare_digest(None, "abc"))
        self.assertFalse(safe_compare_digest("abc", None))


class TestZabbixReceiver(EnhancedTestCase):
    """zabbix_webhook_receiver is allow_guest=True and echoed str(e) to the caller."""

    def _receiver_call_1164(self, signature):
        frappe.response.pop("http_status_code", None)
        before_logs = len(frappe.local.message_log)
        before_errors = _error_log_count_1164()
        with _conf(zabbix_webhook_secret=ZABBIX_SECRET):
            with _real_request({"X-Zabbix-Signature": signature}):
                with self.as_user("Guest"):
                    result = zabbix_integration.zabbix_webhook_receiver()
        return {
            "result": result,
            "status": frappe.response.get("http_status_code"),
            "message_log": list(frappe.local.message_log)[before_logs:],
            "error_logs": _error_log_count_1164() - before_errors,
        }

    def test_non_ascii_signature_is_refused_like_a_wrong_ascii_one(self):
        wrong = self._receiver_call_1164(WRONG_ASCII)
        non_ascii = self._receiver_call_1164(NON_ASCII)
        self.assertEqual(wrong["status"], 401)
        self.assertEqual(wrong["result"]["message"], "Invalid or missing webhook signature")
        self.assertEqual(non_ascii, wrong)

    def test_valid_signature_still_passes_the_gate(self):
        """Control: the gate must still ACCEPT a genuine signature."""
        body = b"{}"
        good = hmac.new(ZABBIX_SECRET.encode(), body, hashlib.sha256).hexdigest()
        with _conf(zabbix_webhook_secret=ZABBIX_SECRET):
            with _real_request({"X-Zabbix-Signature": good}, body=body):
                self.assertTrue(zabbix_integration.validate_webhook_signature())


class TestZabbixTokenGate(EnhancedTestCase):
    def _gate(self, token):
        with _conf(zabbix_api_token=ZABBIX_TOKEN, zabbix_allowed_ips=[], zabbix_allow_guest=False):
            with _real_request({"X-Zabbix-Token": token}):
                with self.as_user("Guest"):
                    return zabbix_integration.is_valid_request()

    def test_non_ascii_token_is_refused_not_raised(self):
        self.assertFalse(self._gate(WRONG_ASCII))
        self.assertFalse(self._gate(NON_ASCII))

    def test_correct_token_is_accepted(self):
        self.assertTrue(self._gate(ZABBIX_TOKEN))


class TestMollieWebhookAuthentication(EnhancedTestCase):
    """Real flow: pg._authenticate_and_parse_subscription_payload, live mode."""

    def _mollie_auth_1164(self, signature):
        body = _json_event(payment_id="tr_1164", subscription_id="sub_1164")
        before_logs = len(frappe.local.message_log)
        before_errors = _error_log_count_1164()
        with _mollie_auth_config(test_mode=False):
            with install_fake_request(body, signature=signature):
                parsed, error = pg._authenticate_and_parse_subscription_payload()
        return {
            "parsed": parsed,
            "error": error,
            "message_log": list(frappe.local.message_log)[before_logs:],
            "error_logs": _error_log_count_1164() - before_errors,
        }

    def test_non_ascii_signature_is_refused_like_a_wrong_ascii_one(self):
        self.expectErrorLog("Webhook Security Alert")
        self.expectErrorLog("Mollie Security - CRITICAL")
        wrong = self._mollie_auth_1164("sha256=" + "0" * 64)
        non_ascii = self._mollie_auth_1164("sha256=" + NON_ASCII)
        self.assertIsNone(wrong["parsed"])
        self.assertEqual(wrong["error"]["status"], "error")
        self.assertEqual(non_ascii, wrong)
        self.assertNotIn("non-ASCII", str(non_ascii["error"]))

    def test_valid_signature_is_accepted(self):
        """Control: a genuine signature still authenticates."""
        body = _json_event(payment_id="tr_1164", subscription_id="sub_1164")
        parsed = self._auth_valid(body)
        self.assertEqual(parsed["subscription_id"], "sub_1164")

    def _auth_valid(self, body):
        with _mollie_auth_config(test_mode=False):
            with install_fake_request(body, signature=sign_payload(body, WEBHOOK_SECRET)):
                parsed, error = pg._authenticate_and_parse_subscription_payload()
        self.assertIsNone(error)
        return parsed


class TestDeadAndSelfLimitedSites(EnhancedTestCase):
    """Sites with no production caller (or authenticated-only): direct calls."""

    def test_membership_verify_signature(self):
        from verenigingen.verenigingen.doctype.membership.membership import verify_signature

        good = hmac.new(b"k1164", b"payload", hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature("payload", good, "k1164"))
        self.assertFalse(verify_signature("payload", WRONG_ASCII, "k1164"))
        self.assertFalse(verify_signature("payload", NON_ASCII, "k1164"))

    def test_ing_checkout_verify_webhook_signature(self):
        from verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security import (
            verify_webhook_signature,
        )

        good = hmac.new(b"k1164", b"payload", hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(b"payload", good, "k1164"))
        self.assertFalse(verify_webhook_signature(b"payload", WRONG_ASCII, "k1164"))
        self.assertFalse(verify_webhook_signature(b"payload", NON_ASCII, "k1164"))

    def test_csrf_validate_token_refuses_non_ascii_as_csrf_error(self):
        from verenigingen.utils.security.csrf_protection import CSRFError, CSRFProtection

        prev = frappe.session.data.get("csrf_token")
        frappe.session.data["csrf_token"] = "csrf-1164"
        try:
            self.assertTrue(CSRFProtection.validate_token("csrf-1164"))
            for bad in (WRONG_ASCII, NON_ASCII):
                with self.assertRaises(CSRFError):
                    CSRFProtection.validate_token(bad)
        finally:
            if prev is None:
                frappe.session.data.pop("csrf_token", None)
            else:
                frappe.session.data["csrf_token"] = prev

    def test_mollie_utils_security_manager(self):
        from verenigingen.verenigingen_payments.mollie.utils.security import WebhookSecurityManager

        manager = object.__new__(WebhookSecurityManager)
        manager.settings = {"webhook_secret": "k1164", "signature_validation": True}
        data = {"id": "tr_1"}
        good = manager._calculate_signature('{"id":"tr_1"}', "k1164")
        self.assertTrue(manager.validate_webhook_signature(data, {"X-Mollie-Signature": good}))
        self.assertFalse(manager.validate_webhook_signature(data, {"X-Mollie-Signature": WRONG_ASCII}))
        self.assertFalse(manager.validate_webhook_signature(data, {"X-Mollie-Signature": NON_ASCII}))

    def test_core_security_manager_refuses_identically(self):
        from verenigingen.verenigingen_payments.core.security.mollie_security_manager import (
            MollieSecurityManager,
            SecurityException,
        )

        class _Settings:
            def get_webhook_secret(self):
                return "k1164"

        manager = object.__new__(MollieSecurityManager)
        manager.settings = _Settings()
        outcomes = []
        # Mock justified: the alert sink writes Error Log / audit rows; only the
        # comparison outcome and the raised message are under test.
        with patch.object(MollieSecurityManager, "_create_security_alert"):
            for bad in (WRONG_ASCII, NON_ASCII):
                with self.assertRaises(SecurityException) as caught:
                    manager.validate_webhook_signature("payload", bad)
                outcomes.append(str(caught.exception))
        self.assertEqual(outcomes[0], outcomes[1])

    def test_mollie_payment_webhook_validator_refuses_identically(self):
        from verenigingen.verenigingen_payments.mollie.api import payment_webhook

        outcomes = []
        with patch(
            "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings."
            "MollieSettings.get_webhook_secret",
            return_value="k1164",
        ):
            for bad in (WRONG_ASCII, NON_ASCII):
                with install_fake_request("{}", signature=bad):
                    before = len(frappe.local.message_log)
                    with self.assertRaises(frappe.PermissionError) as caught:
                        payment_webhook._validate_webhook_signature()
                    # __frappe_exc_id is a per-raise random id; compare everything else.
                    logged = [
                        {k: v for k, v in m.items() if k != "__frappe_exc_id"}
                        for m in frappe.local.message_log[before:]
                    ]
                    outcomes.append((str(caught.exception), logged))
        self.assertEqual(outcomes[0], outcomes[1])
