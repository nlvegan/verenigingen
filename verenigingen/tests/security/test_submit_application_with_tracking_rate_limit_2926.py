"""#2926: the live /word-lid route is ``submit_application_with_tracking``, a thin wrapper.

Its only tight limit (10/hour/IP, the flow mails any address) used to be the callee's own
``@rate_limit``, so splitting the pair (the #2280 pattern: call an undecorated impl) would have
silently dropped it from the live route. The wrapper now carries its own limit.

Fault injection, stated: ``_without_callee_limit`` swaps the module's ``submit_application`` for the same
function with only its ``@rate_limit`` layer removed, which is exactly the state a #2280-style sweep would leave. Everything
else is the real decorated wrapper driven over a real werkzeug Request with a real ``request_ip``.
"""

import random
from contextlib import contextmanager
from unittest import mock

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.api import membership_application as ma
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

LIMIT = 10


def _below_the_rate_limiter(fn):
    """The callee as it would be with its ``@rate_limit`` layer removed (everything else kept)."""
    while fn.__code__.co_filename.rsplit("/", 1)[-1] != "rate_limiter.py":
        fn = fn.__wrapped__
    return fn.__wrapped__


def _forget_submit_rl_counters_2926(ip):
    for fn in (ma.submit_application_with_tracking, ma.submit_application):
        counter = f"{fn.__module__}.{fn.__qualname__}"
        frappe.cache.delete_keys(f"rl:{counter}:{ip}")


class TestSubmitApplicationWithTrackingRateLimit2926(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._previous = (
            getattr(frappe.local, "request", None),
            getattr(frappe.local, "request_ip", None),
            frappe.session.user,
        )
        self.addCleanup(self._restore_request_state_2926)
        self.ip = self._new_ip()
        frappe.set_user("Guest")

    def _restore_request_state_2926(self):
        for ip in getattr(self, "ips", []):
            _forget_submit_rl_counters_2926(ip)
        frappe.local.request, frappe.local.request_ip = self._previous[:2]  # Mock justified: restores the process-level request state; frappe.rate_limit only acts when a request exists
        frappe.set_user(self._previous[2])

    def _new_ip(self):
        ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        self.ips = getattr(self, "ips", []) + [ip]
        _forget_submit_rl_counters_2926(ip)
        return ip

    def _arrive_from(self, ip):
        frappe.local.request = Request(EnvironBuilder(method="POST").get_environ())  # Mock justified: a real werkzeug Request is the precondition for frappe.rate_limit to run at all
        frappe.local.request_ip = ip  # Mock justified: request_ip is what the limiter keys on; no HTTP server exists in a unit run

    @contextmanager
    def _without_callee_limit(self):
        with mock.patch.object(ma, "submit_application", _below_the_rate_limiter(ma.submit_application)):
            yield

    def _hits_until_refused(self, ip, ceiling=LIMIT + 5):
        self._arrive_from(ip)
        for hit in range(1, ceiling + 1):
            try:
                ma.submit_application_with_tracking()
            except frappe.RateLimitExceededError:
                return hit
        return None

    def test_wrapper_alone_enforces_the_hourly_cap(self):
        with self._without_callee_limit():
            self.assertEqual(self._hits_until_refused(self.ip), LIMIT + 1)

    def test_real_pair_still_allows_exactly_the_cap(self):
        # Control: the added limit must not halve or tighten the cap (double counting).
        self.assertEqual(self._hits_until_refused(self.ip), LIMIT + 1)

    def test_bucket_is_per_ip_not_shared_by_every_anonymous_visitor(self):
        with self._without_callee_limit():
            self.assertEqual(self._hits_until_refused(self.ip), LIMIT + 1)
            other = self._new_ip()
            self.assertEqual(self._hits_until_refused(other), LIMIT + 1, "a second visitor has its own budget")

    def test_wrapper_is_still_whitelisted_for_guests(self):
        fn = ma.submit_application_with_tracking
        self.assertIn(fn, frappe.whitelisted)
        self.assertIn(fn, frappe.guest_methods)
