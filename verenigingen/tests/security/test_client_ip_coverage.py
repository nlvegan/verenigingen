"""
Coverage + behavioural tests for verenigingen/utils/security/client_ip.py

This is the lowest-covered security module. Client IP extraction from request
headers is largely PURE logic. These tests build real Werkzeug request objects
(via EnvironBuilder) and bind them to frappe.local.request, then assert the
RESOLVED client IP for a range of proxy / X-Forwarded-For scenarios.

The single most important guarantee is anti-spoofing: an untrusted client that
forges an X-Forwarded-For header MUST NOT be able to make the framework believe
it has a different (e.g. internal/allowlisted) IP. See
test_forged_xff_from_untrusted_client_is_ignored.
"""

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security import client_ip as cip
from verenigingen.utils.security.client_ip import (
    _get_trusted_proxy_networks,
    _is_trusted_proxy,
    _parse_ip_network,
    _parse_x_forwarded_for,
    get_client_ip,
    get_client_ip_with_info,
)


class TestClientIPCoverage(VereningingenTestCase):
    """Real-request IP resolution + pure-helper coverage."""

    def setUp(self):
        super().setUp()
        # Remember whatever request context the harness set up so we can restore it.
        self._orig_request = getattr(frappe.local, "request", None)

    def tearDown(self):
        # Restore the original request so we don't leak our fabricated requests.
        frappe.local.request = self._orig_request
        super().tearDown()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _bind_request(self, remote_addr, headers=None):
        """Bind a real Werkzeug request to frappe.local.request and return it."""
        builder = EnvironBuilder(
            environ_base={"REMOTE_ADDR": remote_addr},
            headers=headers or {},
        )
        request = Request(builder.get_environ())
        frappe.local.request = request
        return request

    # ------------------------------------------------------------------
    # _parse_ip_network (pure)
    # ------------------------------------------------------------------
    def test_parse_ip_network_single_ipv4_becomes_slash32(self):
        net = _parse_ip_network("192.168.1.1")
        self.assertIsNotNone(net)
        self.assertEqual(str(net), "192.168.1.1/32")

    def test_parse_ip_network_single_ipv6_becomes_slash128(self):
        net = _parse_ip_network("::1")
        self.assertIsNotNone(net)
        self.assertEqual(str(net), "::1/128")

    def test_parse_ip_network_cidr_preserved(self):
        net = _parse_ip_network("10.0.0.0/8")
        self.assertIsNotNone(net)
        self.assertEqual(str(net), "10.0.0.0/8")

    def test_parse_ip_network_invalid_returns_none(self):
        self.assertIsNone(_parse_ip_network("not-an-ip"))

    def test_parse_ip_network_invalid_cidr_returns_none(self):
        # "/" present but not a valid network -> hits the ip_network ValueError branch
        self.assertIsNone(_parse_ip_network("999.999.999.999/8"))

    # ------------------------------------------------------------------
    # _parse_x_forwarded_for (pure)
    # ------------------------------------------------------------------
    def test_parse_xff_empty_returns_empty_list(self):
        self.assertEqual(_parse_x_forwarded_for(""), [])

    def test_parse_xff_simple_chain_preserves_order(self):
        self.assertEqual(
            _parse_x_forwarded_for("203.0.113.7, 10.0.0.5"),
            ["203.0.113.7", "10.0.0.5"],
        )

    def test_parse_xff_strips_ipv4_port(self):
        self.assertEqual(_parse_x_forwarded_for("1.2.3.4:5678"), ["1.2.3.4"])

    def test_parse_xff_strips_ipv6_bracket_port(self):
        # "[::1]:9000" -> "::1" (bracket+port branch)
        self.assertEqual(_parse_x_forwarded_for("[::1]:9000"), ["::1"])

    def test_parse_xff_skips_blank_entries(self):
        self.assertEqual(_parse_x_forwarded_for("1.2.3.4, , 5.6.7.8"), ["1.2.3.4", "5.6.7.8"])

    # ------------------------------------------------------------------
    # _get_trusted_proxy_networks / _is_trusted_proxy
    # ------------------------------------------------------------------
    def test_default_trusted_networks_include_private_ranges(self):
        networks = _get_trusted_proxy_networks()
        # Default config trusts private ranges; loopback + RFC1918 must be present.
        self.assertTrue(_is_trusted_proxy("127.0.0.1", networks))
        self.assertTrue(_is_trusted_proxy("10.0.0.5", networks))
        self.assertTrue(_is_trusted_proxy("192.168.1.1", networks))

    def test_public_ip_is_not_trusted_by_default(self):
        networks = _get_trusted_proxy_networks()
        self.assertFalse(_is_trusted_proxy("8.8.8.8", networks))

    def test_is_trusted_proxy_rejects_sentinels(self):
        networks = _get_trusted_proxy_networks()
        self.assertFalse(_is_trusted_proxy("unknown", networks))
        self.assertFalse(_is_trusted_proxy("test_environment", networks))
        self.assertFalse(_is_trusted_proxy("", networks))

    def test_is_trusted_proxy_rejects_malformed_ip(self):
        networks = _get_trusted_proxy_networks()
        # Unparseable IP hits the ValueError branch -> False (fail closed).
        self.assertFalse(_is_trusted_proxy("garbage", networks))

    def test_ipv6_loopback_is_trusted(self):
        networks = _get_trusted_proxy_networks()
        self.assertTrue(_is_trusted_proxy("::1", networks))

    # ------------------------------------------------------------------
    # get_client_ip - off-request / sentinel paths
    # ------------------------------------------------------------------
    def test_no_request_returns_test_environment(self):
        frappe.local.request = None
        self.assertEqual(get_client_ip(), "test_environment")

    def test_remote_addr_unknown_returns_unknown(self):
        # Build a request, then strip REMOTE_ADDR to exercise the "unknown" branch.
        request = self._bind_request("10.0.0.5")
        request.environ.pop("REMOTE_ADDR", None)
        self.assertEqual(get_client_ip(), "unknown")

    # ------------------------------------------------------------------
    # get_client_ip - untrusted remote (no proxy trust)
    # ------------------------------------------------------------------
    def test_untrusted_remote_returns_remote_addr(self):
        # Public REMOTE_ADDR, no XFF -> just the connecting IP.
        self._bind_request("203.0.113.99")
        self.assertEqual(get_client_ip(), "203.0.113.99")

    def test_forged_xff_from_untrusted_client_is_ignored(self):
        """SECURITY: an untrusted client forging X-Forwarded-For must NOT spoof its IP.

        The connecting client (REMOTE_ADDR 8.8.8.8) is NOT a trusted proxy, so its
        X-Forwarded-For header (claiming 127.0.0.1, a privileged loopback address)
        MUST be ignored. The resolved IP must be the real connecting IP, 8.8.8.8.
        """
        self._bind_request("8.8.8.8", headers={"X-Forwarded-For": "127.0.0.1"})
        resolved = get_client_ip()
        self.assertEqual(
            resolved,
            "8.8.8.8",
            "Forged X-Forwarded-For from an untrusted client was honoured -> IP spoofing!",
        )
        self.assertNotEqual(resolved, "127.0.0.1")

    # ------------------------------------------------------------------
    # get_client_ip - trusted proxy chains
    # ------------------------------------------------------------------
    def test_trusted_proxy_returns_real_client_from_xff(self):
        # REMOTE_ADDR is a trusted private proxy; the leftmost public IP is the client.
        self._bind_request("10.0.0.5", headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.5"})
        self.assertEqual(get_client_ip(), "203.0.113.7")

    def test_trusted_proxy_walks_chain_right_to_left(self):
        """First non-trusted IP scanning from the right is the real client."""
        self._bind_request(
            "10.0.0.1",
            headers={"X-Forwarded-For": "198.51.100.23, 10.1.1.1, 10.0.0.1"},
        )
        self.assertEqual(get_client_ip(), "198.51.100.23")

    def test_trusted_proxy_no_xff_returns_proxy_ip(self):
        # Trusted proxy but no X-Forwarded-For header -> falls back to proxy IP.
        self._bind_request("10.0.0.5")
        self.assertEqual(get_client_ip(), "10.0.0.5")

    def test_trusted_proxy_all_hops_trusted_returns_remote_addr(self):
        """If every hop in the chain is trusted, return the non-spoofable
        connecting address, NOT the attacker-controllable leftmost XFF entry.

        Security regression guard (audit #6): the leftmost XFF value can be
        forged by any client, so returning it would let an attacker match a
        private-IP allowlist or rotate per-IP rate-limit buckets.
        """
        self._bind_request(
            "10.0.0.1",
            headers={"X-Forwarded-For": "192.168.1.1, 10.1.1.1, 10.0.0.1"},
        )
        self.assertEqual(get_client_ip(), "10.0.0.1")

    # ------------------------------------------------------------------
    # get_client_ip_with_info
    # ------------------------------------------------------------------
    def test_get_client_ip_with_info_no_request(self):
        frappe.local.request = None
        info = get_client_ip_with_info()
        self.assertEqual(info["client_ip"], "test_environment")
        self.assertFalse(info["is_proxied"])
        self.assertEqual(info["trust_chain"], [])
        self.assertIsNone(info["remote_addr"])

    def test_get_client_ip_with_info_proxied(self):
        self._bind_request("10.0.0.5", headers={"X-Forwarded-For": "203.0.113.7"})
        info = get_client_ip_with_info()
        self.assertEqual(info["client_ip"], "203.0.113.7")
        self.assertEqual(info["remote_addr"], "10.0.0.5")
        self.assertTrue(info["is_proxied"])
        self.assertEqual(info["trust_chain"], ["203.0.113.7"])
        self.assertEqual(info["x_forwarded_for"], "203.0.113.7")

    def test_get_client_ip_with_info_direct_public(self):
        self._bind_request("203.0.113.99")
        info = get_client_ip_with_info()
        self.assertEqual(info["client_ip"], "203.0.113.99")
        self.assertEqual(info["remote_addr"], "203.0.113.99")
        self.assertFalse(info["is_proxied"])
        self.assertEqual(info["trust_chain"], [])
        self.assertIsNone(info["x_forwarded_for"])
