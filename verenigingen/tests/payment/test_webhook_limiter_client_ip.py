"""
The webhook rate limiter must be keyed on the TRUSTED client IP, not on the
leftmost X-Forwarded-For entry (issue #1764).

Frappe sets ``frappe.local.request_ip`` from the LEFTMOST X-Forwarded-For
entry, which the client chooses. Keying the per-IP bucket on it lets an
attacker mint a fresh bucket per request by varying that header.

These tests use REAL werkzeug requests and Frappe's own
``HTTPRequest.set_request_ip`` (so ``request_ip`` is derived exactly as in
production), then call the real webhook entry points with the REAL limiter.
Nothing about IP resolution or the limiter is stubbed.

Topology modelled: a trusted proxy (127.0.0.1, the default trusted range)
appends the real client address to a client-supplied X-Forwarded-For.
"""

from datetime import timedelta

import frappe
from frappe.auth import HTTPRequest
from frappe.utils import now_datetime
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.ing_checkout.api import webhook as ing_webhook
from verenigingen.verenigingen_payments.ing_checkout.utils import webhook_security as ing_security
from verenigingen.verenigingen_payments.mollie.utils.webhook_security import authenticate_mollie_webhook
from verenigingen.verenigingen_payments.ponto.api import webhook as ponto_webhook
from verenigingen.verenigingen_payments.utils.webhook_rate_limiter import (
    get_webhook_rate_limiter,
    reset_rate_limiter,
)

PROXY = "127.0.0.1"
REAL_CLIENT = "203.0.113.77"


def _spoofed(n):
    return f"198.51.100.{n}"


class _WebhookRequestCase(VereningingenTestCase):
    """Real-request plumbing shared by the test classes below (no tests here)."""

    def setUp(self):
        super().setUp()
        reset_rate_limiter()
        self.addCleanup(reset_rate_limiter)
        self._orig_request = getattr(frappe.local, "request", None)
        self._orig_request_ip = getattr(frappe.local, "request_ip", None)
        self._orig_form_dict = getattr(frappe.local, "form_dict", None)
        self.addCleanup(self._restore_webhook_request_state)
        frappe.local.form_dict = frappe._dict({})
        # The handlers reach their signature check with an empty body and log
        # the refusal; that logging is the expected path here, not a leak.
        self.expectErrorLog("Security", "Ing_Checkout", "Ponto", "Mollie", "Webhook")

    def _restore_webhook_request_state(self):
        frappe.local.request = self._orig_request
        frappe.local.request_ip = self._orig_request_ip
        frappe.local.form_dict = self._orig_form_dict

    def _install_real_webhook_request(self, remote_addr=PROXY, xff=None, headers=None):
        hdrs = dict(headers or {})
        if xff is not None:
            hdrs["X-Forwarded-For"] = xff
        environ = EnvironBuilder(
            method="POST", path="/api/method/webhook", headers=hdrs, data=b"{}"
        ).get_environ()
        environ["REMOTE_ADDR"] = remote_addr
        frappe.local.request = Request(environ)
        # Frappe's own derivation of request_ip (frappe/auth.py)
        HTTPRequest.__new__(HTTPRequest).set_request_ip()

    def _call_quietly(self, fn):
        try:
            return fn()
        except Exception:
            # Past the limiter the handlers fail on signature/settings; only
            # which bucket the limiter charged matters here.
            return None

    def _buckets(self):
        return set(get_webhook_rate_limiter().ip_requests)


class TestWebhookLimiterClientIp(_WebhookRequestCase):

    def test_premise_frappe_request_ip_is_the_spoofed_value(self):
        """Control: without this the rest of the file proves nothing."""
        self._install_real_webhook_request(xff=f"{_spoofed(1)}, {REAL_CLIENT}")
        self.assertEqual(frappe.local.request_ip, _spoofed(1))

    def _assert_charged_to_real_client(self, call):
        self._install_real_webhook_request(xff=f"{_spoofed(1)}, {REAL_CLIENT}")
        self._call_quietly(call)
        self.assertEqual(self._buckets(), {REAL_CLIENT})

    def test_mollie_charges_the_trusted_client_ip(self):
        self._assert_charged_to_real_client(authenticate_mollie_webhook)

    def test_ponto_charges_the_trusted_client_ip(self):
        self._assert_charged_to_real_client(ponto_webhook.handle_ponto_webhook)

    def test_ing_payment_charges_the_trusted_client_ip(self):
        self._assert_charged_to_real_client(ing_webhook.handle_payment)

    def test_ing_mandate_charges_the_trusted_client_ip(self):
        self._assert_charged_to_real_client(ing_webhook.handle_mandate)

    def test_ing_direct_debit_charges_the_trusted_client_ip(self):
        self._assert_charged_to_real_client(ing_webhook.handle_direct_debit)

    def test_rotating_the_spoofed_entry_does_not_mint_fresh_buckets(self):
        """Behavioural: ip_limit requests pass, the next is refused however
        the leftmost X-Forwarded-For entry is varied."""
        limiter = get_webhook_rate_limiter()
        limiter.ip_limit = 3
        results = []
        for n in range(1, 6):
            self._install_real_webhook_request(xff=f"{_spoofed(n)}, {REAL_CLIENT}")
            try:
                authenticate_mollie_webhook()
                results.append("allowed")
            except Exception as e:
                results.append("limited" if "Rate limit exceeded" in str(e) else "allowed")
        self.assertEqual(results, ["allowed"] * 3 + ["limited"] * 2)

    def test_control_distinct_real_clients_get_distinct_buckets(self):
        """The fix must not collapse everyone into one bucket (the REMOTE_ADDR
        wrong-fix puts every client behind the proxy into 127.0.0.1)."""
        for client in ("203.0.113.10", "203.0.113.11"):
            self._install_real_webhook_request(xff=client)
            self._call_quietly(authenticate_mollie_webhook)
        self.assertEqual(self._buckets(), {"203.0.113.10", "203.0.113.11"})

    def test_direct_connection_ignores_xff_entirely(self):
        """REMOTE_ADDR not a trusted proxy: XFF is attacker input, even the
        rightmost entry. Bucket is the connecting address."""
        self._install_real_webhook_request(remote_addr="192.0.2.50", xff=f"{_spoofed(9)}, 192.0.2.99")
        self._call_quietly(authenticate_mollie_webhook)
        self.assertEqual(self._buckets(), {"192.0.2.50"})


class TestIngIpAllowlistClientIp(_WebhookRequestCase):
    """Same defect, security-decision variant: the ING (Pay.nl) source-IP check
    ``get_request_ip`` also took the leftmost X-Forwarded-For entry, so a
    spoofed Pay.nl address was accepted as "IP validated" and, per
    ``verify_ing_checkout_webhook``, an IP-validated request needs no signature.
    """

    PAYNL_IP = "192.0.2.200"

    def setUp(self):
        super().setUp()
        self._orig_cache = ing_security._paynl_ip_cache
        self.addCleanup(setattr, ing_security, "_paynl_ip_cache", self._orig_cache)
        # Seed the hourly Pay.nl address cache (the module's own seam) so no
        # HTTP call is made; verification itself runs for real.
        ing_security._paynl_ip_cache = {
            "ips": [self.PAYNL_IP],
            "last_updated": now_datetime() - timedelta(minutes=1),
        }

    def test_get_request_ip_is_the_trusted_client_not_the_leftmost_entry(self):
        self._install_real_webhook_request(xff=f"{self.PAYNL_IP}, {REAL_CLIENT}")
        self.assertEqual(ing_security.get_request_ip(), REAL_CLIENT)

    def test_get_request_ip_direct_connection_ignores_xff_and_x_real_ip(self):
        self._install_real_webhook_request(
            remote_addr="192.0.2.50",
            xff=self.PAYNL_IP,
            headers={"X-Real-IP": self.PAYNL_IP},
        )
        self.assertEqual(ing_security.get_request_ip(), "192.0.2.50")

    def test_spoofed_paynl_address_does_not_authenticate(self):
        self._install_real_webhook_request(xff=f"{self.PAYNL_IP}, {REAL_CLIENT}")
        with self.assertRaises(ing_security.INGCheckoutWebhookError):
            ing_security.verify_ing_checkout_webhook(b"{}", signature=None)

    def test_control_genuine_paynl_address_still_validates(self):
        """A real row for the wrong behaviour to find: the allowlist must still
        accept the genuine sender, or an always-reject fix would pass above."""
        self._install_real_webhook_request(xff=self.PAYNL_IP)
        self.assertTrue(ing_security.verify_ing_checkout_webhook(b"{}", signature=None))

    def test_client_supplied_x_real_ip_through_a_trusted_proxy_is_not_trusted(self):
        """nginx here sets no X-Real-IP, so a client-supplied one reaches the app
        from the trusted proxy. It must neither become the IP nor authenticate."""
        self._install_real_webhook_request(headers={"X-Real-IP": self.PAYNL_IP})
        self.assertEqual(ing_security.get_request_ip(), PROXY)
        with self.assertRaises(ing_security.INGCheckoutWebhookError):
            ing_security.verify_ing_checkout_webhook(b"{}", signature=None)
