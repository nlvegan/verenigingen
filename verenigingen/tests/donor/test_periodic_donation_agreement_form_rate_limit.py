# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
Regression tests for the periodic donation agreement web form's rate limiter
(verenigingen/verenigingen/web_form/periodic_donation_agreement_form/periodic_donation_agreement_form.py).

Two independent bugs, both from the same underlying cause -- raw
frappe.cache().get() returns bytes on a cache hit, never an int:

1. increment_rate_limit() called frappe.cache().set(key, val,
   expires_in_sec=3600). `expires_in_sec` is set_value()'s kwarg, not raw
   redis.Redis.set()'s (`ex=`) -- this raised TypeError on the very FIRST call,
   so the counter was never written and check_rate_limit() always read 0.
2. Even once that call succeeds, `current_count + 1` (increment_rate_limit)
   and `current_count >= RATE_LIMIT_SUBMISSIONS_PER_HOUR` (check_rate_limit)
   both break on a bytes value once a previous call has stored one.

See GitHub issue #878. Uses the real Redis-backed frappe.cache(), no mocking.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
    RATE_LIMIT_CACHE_PREFIX,
    RATE_LIMIT_SUBMISSIONS_PER_HOUR,
    check_rate_limit,
    increment_rate_limit,
)


class TestPeriodicDonationAgreementFormRateLimit(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.cache_key = f"{RATE_LIMIT_CACHE_PREFIX}:{frappe.session.user}"
        # The code under test stores this key via raw redis .get()/.set()
        # (no make_key() prefixing), so it must be cleared the same way --
        # delete_value() prefixes the key and would delete the wrong entry.
        frappe.cache().delete(self.cache_key)
        self.addCleanup(lambda: frappe.cache().delete(self.cache_key))

    def test_increment_does_not_raise_on_first_call(self):
        """Regression: increment_rate_limit() must not raise TypeError on its
        very first call (the wrong `expires_in_sec` kwarg to raw .set())."""
        increment_rate_limit()  # must not raise
        stored = frappe.cache().get(self.cache_key)
        self.assertIsInstance(stored, (bytes, bytearray))
        self.assertEqual(int(stored), 1)

    def test_repeated_increments_are_counted_correctly(self):
        """Regression: each increment reads back a bytes counter from the
        previous call and must add to it, not silently reset/break."""
        for _ in range(RATE_LIMIT_SUBMISSIONS_PER_HOUR):
            increment_rate_limit()
        stored = frappe.cache().get(self.cache_key)
        self.assertEqual(int(stored), RATE_LIMIT_SUBMISSIONS_PER_HOUR)

    def test_check_rate_limit_trips_after_limit_reached(self):
        """Regression: check_rate_limit() must throw once the (bytes) counter
        reaches the configured limit -- not silently allow forever."""
        for _ in range(RATE_LIMIT_SUBMISSIONS_PER_HOUR):
            increment_rate_limit()

        stored = frappe.cache().get(self.cache_key)
        self.assertIsInstance(stored, (bytes, bytearray), "test setup assumption: raw cache stores bytes")

        self.expectErrorLog("Agreement Form Rate Limit")
        with self.assertRaises(frappe.RateLimitExceededError):
            check_rate_limit()
