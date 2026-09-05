# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
Regression tests for verenigingen/api/membership_application.py::check_rate_limit().

frappe.cache().get() returns bytes on a cache hit (this call uses raw
redis .get()/.setex(), not frappe's pickling get_value()/set_value()), so a bare
`bytes >= int` comparison raises TypeError. Before the fix, that TypeError was
swallowed by the function's own `except Exception: return True`, so the endpoint
silently failed OPEN (unlimited) starting from the SECOND call in any window --
see GitHub issue #878.

Uses the real Redis-backed frappe.cache(), no mocking: the bug is specifically
about what raw redis returns, so mocking it away would hide the defect.
"""

import frappe

from verenigingen.api.membership_application import check_rate_limit
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMembershipApplicationRateLimit(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # Isolate this test's counter from any other test/run using the same
        # (endpoint, client_ip) cache key.
        self.endpoint = "test_rate_limit_878"
        self.client_ip = "127.0.0.1"
        self.cache_key = f"rate_limit:{self.endpoint}:{self.client_ip}"
        # The code under test stores this key via raw redis .get()/.setex()
        # (no make_key() prefixing), so it must be cleared the same way --
        # delete_value() prefixes the key and would delete the wrong entry.
        frappe.cache().delete(self.cache_key)
        self.addCleanup(lambda: frappe.cache().delete(self.cache_key))

        # check_rate_limit() reads the IP from frappe.local.request, which is
        # unset in a test/console context -- stub it exactly like the real
        # request environ this function depends on.
        class _FakeRequest:
            environ = {"REMOTE_ADDR": "127.0.0.1"}

        original_request = getattr(frappe.local, "request", None)
        frappe.local.request = _FakeRequest()
        self.addCleanup(lambda: setattr(frappe.local, "request", original_request))

    def test_second_call_within_window_still_enforces_the_limit(self):
        """Regression: the SECOND call within a window must not fail open.

        Call 0 stores the counter as bytes via raw redis. Call 1 must read
        that bytes value back as an int and keep counting correctly -- it must
        NOT raise (silently caught) and return True regardless of the count.
        """
        limit = 2

        # Call 0: no cache entry yet -> allowed, counter becomes 1 (as bytes).
        self.assertTrue(check_rate_limit(self.endpoint, limit_per_hour=limit))
        stored = frappe.cache().get(self.cache_key)
        self.assertIsInstance(stored, (bytes, bytearray), "test setup assumption: raw cache stores bytes")

        # Call 1: reads back the bytes counter. Before the fix this raised
        # TypeError inside the try block, was swallowed by `except Exception:
        # return True`, and returned True no matter how high the real count was.
        self.assertTrue(check_rate_limit(self.endpoint, limit_per_hour=limit))

        # Call 2: counter is now 2, which has met the limit -- must be refused.
        self.assertFalse(
            check_rate_limit(self.endpoint, limit_per_hour=limit),
            "rate limit did not trip at the configured threshold -- it is failing open",
        )
