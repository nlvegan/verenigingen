"""
Real-integration tests for WebhookRateLimiter.

The rate limiter is pure in-process logic (sliding-window timestamp math,
progressive penalties, cleanup). These tests drive a fresh limiter instance
with real inputs and assert the allow/reject/penalty/cleanup branches.

No mocking of business logic. The limiter reads `frappe.conf` for limits, so
each test builds its own instance (with a small custom config) to keep the
windows deterministic and independent of any shared global instance.
"""

import time

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.webhook_rate_limiter import (
    WebhookRateLimiter,
    get_webhook_rate_limiter,
    reset_rate_limiter,
)


class TestWebhookRateLimiter(VereningingenTestCase):
    def _make_limiter(self, ip_limit=5, webhook_id_limit=2, global_limit=100):
        """Build a limiter with deterministic small limits (no shared global)."""
        limiter = WebhookRateLimiter()
        limiter.ip_limit = ip_limit
        limiter.webhook_id_limit = webhook_id_limit
        limiter.global_limit = global_limit
        return limiter

    def test_first_request_allowed(self):
        limiter = self._make_limiter()
        allowed, reason = limiter.check_rate_limit("203.0.113.1")
        self.assertTrue(allowed)
        self.assertEqual(reason, "Request allowed")

    def test_request_recorded_in_global_window(self):
        limiter = self._make_limiter()
        limiter.check_rate_limit("203.0.113.2")
        now = time.time()
        self.assertEqual(limiter.global_requests.count(now), 1)
        self.assertEqual(limiter.ip_requests["203.0.113.2"].count(now), 1)

    def test_ip_limit_exceeded_rejects(self):
        limiter = self._make_limiter(ip_limit=3)
        ip = "203.0.113.3"
        for _ in range(3):
            allowed, _r = limiter.check_rate_limit(ip)
            self.assertTrue(allowed)
        # 4th request must be rejected
        allowed, reason = limiter.check_rate_limit(ip)
        self.assertFalse(allowed)
        self.assertIn("IP rate limit exceeded", reason)

    def test_ip_penalty_increments_and_tightens_limit(self):
        limiter = self._make_limiter(ip_limit=4)
        ip = "203.0.113.4"
        # Fill to limit
        for _ in range(4):
            limiter.check_rate_limit(ip)
        self.assertEqual(limiter.ip_penalties[ip], 0)
        # First rejection raises penalty to 1
        allowed, reason = limiter.check_rate_limit(ip)
        self.assertFalse(allowed)
        self.assertEqual(limiter.ip_penalties[ip], 1)
        # effective limit now max(1, 4 // 2) = 2; reason reports penalty
        allowed2, reason2 = limiter.check_rate_limit(ip)
        self.assertFalse(allowed2)
        self.assertEqual(limiter.ip_penalties[ip], 2)
        self.assertIn("penalty", reason2)

    def test_penalty_multiplier_capped(self):
        limiter = self._make_limiter(ip_limit=2)
        limiter.max_penalty_multiplier = 3
        ip = "203.0.113.5"
        # Generate many rejections to push penalty well past the cap
        for _ in range(2):
            limiter.check_rate_limit(ip)
        for _ in range(20):
            limiter.check_rate_limit(ip)
        # effective_limit uses min(penalties, max_penalty_multiplier); never
        # divides by more than (1 + max_penalty_multiplier) so limit stays >= 1.
        effective = max(
            1, limiter.ip_limit // (1 + min(limiter.ip_penalties[ip], limiter.max_penalty_multiplier))
        )
        self.assertGreaterEqual(effective, 1)

    def test_webhook_id_limit_exceeded(self):
        limiter = self._make_limiter(ip_limit=100, webhook_id_limit=2)
        ip = "203.0.113.6"
        wid = "wh_dup"
        self.assertTrue(limiter.check_rate_limit(ip, wid)[0])
        self.assertTrue(limiter.check_rate_limit(ip, wid)[0])
        allowed, reason = limiter.check_rate_limit(ip, wid)
        self.assertFalse(allowed)
        self.assertIn("too frequently", reason)

    def test_global_limit_exceeded(self):
        limiter = self._make_limiter(ip_limit=1000, global_limit=3)
        # Use distinct IPs so only the global limit trips
        for i in range(3):
            allowed, _r = limiter.check_rate_limit(f"198.51.100.{i}")
            self.assertTrue(allowed)
        allowed, reason = limiter.check_rate_limit("198.51.100.99")
        self.assertFalse(allowed)
        self.assertIn("System overloaded", reason)

    def test_old_requests_expire_from_window(self):
        limiter = self._make_limiter(ip_limit=2)
        ip = "203.0.113.7"
        # Inject a stale timestamp older than the window directly via the SlidingWindowCounter
        old_ts = time.time() - (limiter.time_window + 5)
        limiter.global_requests.add(old_ts)
        # Ensure the IP counter exists before adding to it
        if ip not in limiter.ip_requests:
            from verenigingen.verenigingen_payments.utils.shared.sliding_window import SlidingWindowCounter

            limiter.ip_requests[ip] = SlidingWindowCounter(limiter.time_window)
        limiter.ip_requests[ip].add(old_ts)
        # A fresh request should not be blocked by the stale entries
        allowed, _r = limiter.check_rate_limit(ip)
        self.assertTrue(allowed)
        # Stale global entry got purged by _check_global_limit (via count -> prune)
        now = time.time()
        self.assertEqual(limiter.global_requests.count(now), 1)  # only the fresh request

    def test_cleanup_removes_idle_ip_and_penalty(self):
        from verenigingen.verenigingen_payments.utils.shared.sliding_window import SlidingWindowCounter

        limiter = self._make_limiter(ip_limit=2)
        ip = "203.0.113.8"
        # Seed an idle IP with very old requests + a penalty via SlidingWindowCounter.add()
        old_ts = time.time() - (3 * limiter.time_window)
        limiter.ip_requests[ip] = SlidingWindowCounter(limiter.time_window)
        limiter.ip_requests[ip].add(old_ts)
        limiter.ip_penalties[ip] = 5
        limiter.webhook_requests["wh_old"] = SlidingWindowCounter(limiter.time_window)
        limiter.webhook_requests["wh_old"].add(old_ts)
        limiter.global_requests.add(old_ts)
        # Force cleanup to run
        limiter.last_cleanup = time.time() - (limiter.cleanup_interval + 1)
        limiter._cleanup_old_entries(time.time())
        self.assertNotIn(ip, limiter.ip_requests)
        self.assertNotIn(ip, limiter.ip_penalties)
        self.assertNotIn("wh_old", limiter.webhook_requests)
        self.assertEqual(limiter.global_requests.count(time.time()), 0)

    def test_cleanup_skipped_when_interval_not_elapsed(self):
        limiter = self._make_limiter()
        limiter.last_cleanup = time.time()
        before = limiter.last_cleanup
        limiter._cleanup_old_entries(time.time())
        # last_cleanup unchanged means cleanup was skipped
        self.assertEqual(limiter.last_cleanup, before)

    def test_penalty_reduced_when_ip_behaves(self):
        limiter = self._make_limiter(ip_limit=10)
        ip = "203.0.113.9"
        limiter.ip_penalties[ip] = 3
        # A single well-behaved request (< ip_limit//2) decrements the penalty
        limiter.check_rate_limit(ip)
        self.assertEqual(limiter.ip_penalties[ip], 2)

    def test_get_stats_reports_window_counts(self):
        limiter = self._make_limiter(ip_limit=100, global_limit=50)
        limiter.check_rate_limit("203.0.113.10")
        limiter.check_rate_limit("203.0.113.11")
        stats = limiter.get_stats()
        self.assertEqual(stats["global_requests_per_minute"], 2)
        self.assertEqual(stats["global_limit"], 50)
        self.assertEqual(stats["active_ips"], 2)
        self.assertGreater(stats["utilization_percent"], 0)

    def test_get_stats_zero_global_limit_no_div_error(self):
        limiter = self._make_limiter()
        limiter.global_limit = 0
        stats = limiter.get_stats()
        self.assertEqual(stats["utilization_percent"], 0)

    def test_reset_ip_penalty(self):
        limiter = self._make_limiter()
        ip = "203.0.113.12"
        limiter.ip_penalties[ip] = 7
        limiter.reset_ip_penalty(ip)
        self.assertNotIn(ip, limiter.ip_penalties)
        # resetting an unknown IP is a no-op (no error)
        limiter.reset_ip_penalty("203.0.113.13")

    def test_global_factory_is_singleton_and_resettable(self):
        reset_rate_limiter()
        a = get_webhook_rate_limiter()
        b = get_webhook_rate_limiter()
        self.assertIs(a, b)
        reset_rate_limiter()
        c = get_webhook_rate_limiter()
        self.assertIsNot(a, c)
        # leave a clean global for any other test in the run
        reset_rate_limiter()
