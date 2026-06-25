"""
Coverage gap-fill for verenigingen_payments/core/resilience/rate_limiter.py

Pure-logic timing/math tests (no DB). Covers:
- TokenBucketRateLimiter: acquire (granted / denied / multi-token), refill math,
  max-token cap, get_available_tokens, wait_for_token success+timeout, get_metrics
  (incl. zero-request grant_rate and average_wait_time guards), reset.
- AdaptiveRateLimiter: on_success -> rate increase after threshold, on_rate_limit
  (with/without retry_after) -> rate decrease & token pause, _increase/_decrease
  clamping to min/max, adapt_from_headers (Remaining / Reset / Retry-After).
- EndpointRateLimiter: per-endpoint limiter creation, acquire success, global-limit
  exhaustion -> deny when not waiting, endpoint-limit exhaustion returns global
  tokens, on_response (429 + success), get_endpoint_metrics, reset_all.
- get_endpoint_rate_limiter singleton.

Timing approach: the token bucket reads time.time() only via last_refill deltas, so
refill math is exercised by setting last_refill into the past (no clock mocking, no
sleeps). The wait path uses a tiny REAL window. time.sleep is never mocked.

Run:
    bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_rate_limiter_coverage_b1
"""

import time
import unittest

from verenigingen.verenigingen_payments.core.resilience.rate_limiter import (
    AdaptiveRateLimiter,
    EndpointRateLimiter,
    TokenBucketRateLimiter,
    get_endpoint_rate_limiter,
)


class TestTokenBucketRateLimiter(unittest.TestCase):
    def test_acquire_grants_when_tokens_available(self):
        rl = TokenBucketRateLimiter(max_tokens=10, refill_rate=1, refill_period=1)
        self.assertTrue(rl.acquire(1))
        self.assertEqual(rl.total_granted, 1)
        self.assertEqual(rl.total_requests, 1)

    def test_acquire_multi_token_deducts_correctly(self):
        rl = TokenBucketRateLimiter(max_tokens=10, refill_rate=1, refill_period=1)
        self.assertTrue(rl.acquire(5))
        self.assertEqual(rl.get_available_tokens(), 5)

    def test_acquire_denied_when_insufficient_and_no_wait(self):
        rl = TokenBucketRateLimiter(max_tokens=3, refill_rate=1, refill_period=1)
        self.assertTrue(rl.acquire(3))
        # Bucket empty now; freeze refill by pinning last_refill to "just now"
        rl.last_refill = time.time()
        denied = rl.acquire(1, wait=False)
        self.assertFalse(denied)
        self.assertEqual(rl.total_denied, 1)

    def test_refill_adds_tokens_based_on_elapsed_time(self):
        rl = TokenBucketRateLimiter(max_tokens=100, refill_rate=5, refill_period=1)
        rl.tokens = 0
        # Pretend 4 refill periods elapsed -> 4 * 5 = 20 tokens
        rl.last_refill = time.time() - 4.5
        self.assertEqual(rl.get_available_tokens(), 20)

    def test_refill_capped_at_max(self):
        rl = TokenBucketRateLimiter(max_tokens=10, refill_rate=5, refill_period=1)
        rl.tokens = 0
        rl.last_refill = time.time() - 100  # would add 500 tokens, but capped
        self.assertEqual(rl.get_available_tokens(), 10)

    def test_partial_period_does_not_refill(self):
        rl = TokenBucketRateLimiter(max_tokens=10, refill_rate=5, refill_period=10)
        rl.tokens = 2
        rl.last_refill = time.time() - 3  # < refill_period -> refill_count == 0
        self.assertEqual(rl.get_available_tokens(), 2)

    def test_wait_for_token_succeeds_after_refill(self):
        # Tiny real window: empty bucket, fast refill so the wait loop grants quickly.
        rl = TokenBucketRateLimiter(max_tokens=5, refill_rate=5, refill_period=0.05)
        rl.tokens = 0
        rl.last_refill = time.time()
        self.assertTrue(rl.wait_for_token(timeout=2.0))
        self.assertGreaterEqual(rl.total_granted, 1)
        self.assertGreater(rl.total_wait_time, 0)

    def test_wait_for_tokens_times_out(self):
        # refill_period far larger than timeout -> never refills within window
        rl = TokenBucketRateLimiter(max_tokens=5, refill_rate=5, refill_period=1000)
        rl.tokens = 0
        rl.last_refill = time.time()
        self.assertFalse(rl.acquire(1, wait=True, timeout=0.3))
        self.assertEqual(rl.total_denied, 1)

    def test_metrics_with_no_requests(self):
        rl = TokenBucketRateLimiter(max_tokens=10, refill_rate=1, refill_period=1)
        m = rl.get_metrics()
        self.assertEqual(m["grant_rate"], 0)
        self.assertEqual(m["average_wait_time"], 0)
        self.assertEqual(m["max_tokens"], 10)

    def test_metrics_after_grants(self):
        rl = TokenBucketRateLimiter(max_tokens=10, refill_rate=1, refill_period=1)
        rl.acquire(1)
        rl.acquire(1)
        m = rl.get_metrics()
        self.assertEqual(m["total_requests"], 2)
        self.assertEqual(m["total_granted"], 2)
        self.assertEqual(m["grant_rate"], 1.0)

    def test_reset_restores_initial_state(self):
        rl = TokenBucketRateLimiter(max_tokens=10, refill_rate=1, refill_period=1)
        rl.acquire(5)
        rl.total_denied = 3
        rl.reset()
        self.assertEqual(rl.get_available_tokens(), 10)
        self.assertEqual(rl.total_requests, 0)
        self.assertEqual(rl.total_granted, 0)
        self.assertEqual(rl.total_denied, 0)
        self.assertEqual(rl.total_wait_time, 0.0)


class TestAdaptiveRateLimiter(unittest.TestCase):
    def test_on_success_increases_rate_after_threshold(self):
        rl = AdaptiveRateLimiter(initial_refill_rate=5.0, max_refill_rate=10.0)
        for _ in range(99):
            rl.on_success()
        self.assertEqual(rl.refill_rate, 5.0)  # not yet
        rl.on_success()  # 100th
        self.assertGreater(rl.refill_rate, 5.0)
        self.assertEqual(rl.consecutive_successes, 0)

    def test_increase_rate_clamped_to_max(self):
        rl = AdaptiveRateLimiter(initial_refill_rate=9.95, max_refill_rate=10.0)
        rl._increase_rate()
        self.assertEqual(rl.refill_rate, 10.0)

    def test_on_rate_limit_decreases_rate(self):
        rl = AdaptiveRateLimiter(initial_refill_rate=8.0, min_refill_rate=1.0)
        rl.on_rate_limit()
        self.assertEqual(rl.refill_rate, 4.0)  # halved
        self.assertIsNotNone(rl.last_rate_limit_time)

    def test_decrease_rate_clamped_to_min(self):
        rl = AdaptiveRateLimiter(initial_refill_rate=1.5, min_refill_rate=1.0)
        rl._decrease_rate()
        self.assertEqual(rl.refill_rate, 1.0)

    def test_on_rate_limit_with_retry_after_pauses_tokens(self):
        rl = AdaptiveRateLimiter(initial_refill_rate=8.0, min_refill_rate=1.0)
        before = time.time()
        rl.on_rate_limit(retry_after=60)
        self.assertEqual(rl.tokens, 0)
        self.assertEqual(rl.retry_after, 60)
        self.assertGreaterEqual(rl.last_refill, before + 59)

    def test_adapt_from_headers_low_remaining_slows_down(self):
        rl = AdaptiveRateLimiter(initial_refill_rate=10.0, min_refill_rate=1.0)
        rl.adapt_from_headers({"X-RateLimit-Remaining": "5"})
        self.assertLess(rl.refill_rate, 10.0)

    def test_adapt_from_headers_high_remaining_no_change(self):
        rl = AdaptiveRateLimiter(initial_refill_rate=10.0, min_refill_rate=1.0)
        rl.adapt_from_headers({"X-RateLimit-Remaining": "500"})
        self.assertEqual(rl.refill_rate, 10.0)

    def test_adapt_from_headers_reset_pauses_until_reset(self):
        rl = AdaptiveRateLimiter()
        future = int(time.time()) + 120
        rl.adapt_from_headers({"X-RateLimit-Reset": str(future)})
        self.assertEqual(rl.tokens, 0)
        self.assertEqual(rl.last_refill, future)

    def test_adapt_from_headers_retry_after_triggers_rate_limit(self):
        rl = AdaptiveRateLimiter(initial_refill_rate=8.0, min_refill_rate=1.0)
        rl.adapt_from_headers({"Retry-After": "30"})
        self.assertEqual(rl.retry_after, 30)
        self.assertEqual(rl.refill_rate, 4.0)


class TestEndpointRateLimiter(unittest.TestCase):
    def test_acquire_creates_endpoint_limiter(self):
        erl = EndpointRateLimiter(global_limit=1000)
        self.assertTrue(erl.acquire("payments", tokens=1, wait=False))
        self.assertIn("payments", erl.endpoint_limiters)

    def test_unknown_endpoint_uses_default_limit(self):
        erl = EndpointRateLimiter(global_limit=1000)
        self.assertTrue(erl.acquire("custom_endpoint", tokens=1, wait=False))
        limiter = erl.endpoint_limiters["custom_endpoint"]
        self.assertEqual(limiter.max_tokens, 60)  # default

    def test_global_limit_exhausted_denies_without_wait(self):
        erl = EndpointRateLimiter(global_limit=5)
        # Drain the global limiter directly and freeze its refill
        erl.global_limiter.tokens = 0
        erl.global_limiter.last_refill = time.time()
        self.assertFalse(erl.acquire("payments", tokens=1, wait=False))

    def test_endpoint_limit_exhausted_returns_global_tokens(self):
        erl = EndpointRateLimiter(global_limit=1000)
        # Prime endpoint limiter, then drain it and freeze refill
        erl.acquire("chargebacks", tokens=1, wait=False)
        ep = erl.endpoint_limiters["chargebacks"]
        ep.tokens = 0
        ep.last_refill = time.time()
        global_before = erl.global_limiter.get_available_tokens()
        result = erl.acquire("chargebacks", tokens=1, wait=False)
        self.assertFalse(result)
        # Global tokens should be restored (acquire took 1 from global then returned it)
        global_after = erl.global_limiter.get_available_tokens()
        self.assertEqual(global_after, global_before)

    def test_on_response_success_and_429(self):
        erl = EndpointRateLimiter(global_limit=1000)
        erl.acquire("payments", tokens=1, wait=False)
        limiter = erl.endpoint_limiters["payments"]
        rate_before = limiter.refill_rate

        erl.on_response("payments", 200, {})
        self.assertEqual(limiter.consecutive_successes, 1)

        erl.on_response("payments", 429, {"Retry-After": "30"})
        self.assertLessEqual(limiter.refill_rate, rate_before)
        self.assertEqual(limiter.consecutive_successes, 0)

    def test_on_response_unknown_endpoint_noop(self):
        erl = EndpointRateLimiter(global_limit=1000)
        # No limiter exists for this endpoint yet -> should not raise
        erl.on_response("never_seen", 200, {})
        self.assertNotIn("never_seen", erl.endpoint_limiters)

    def test_get_endpoint_metrics_includes_global(self):
        erl = EndpointRateLimiter(global_limit=1000)
        erl.acquire("balances", tokens=1, wait=False)
        metrics = erl.get_endpoint_metrics()
        self.assertIn("global", metrics)
        self.assertIn("balances", metrics)

    def test_reset_all_resets_global_and_endpoints(self):
        erl = EndpointRateLimiter(global_limit=1000)
        erl.acquire("payments", tokens=2, wait=False)
        erl.global_limiter.total_requests = 99
        erl.reset_all()
        self.assertEqual(erl.global_limiter.total_requests, 0)
        for limiter in erl.endpoint_limiters.values():
            self.assertEqual(limiter.total_requests, 0)


class TestSingletonAccessor(unittest.TestCase):
    def test_get_endpoint_rate_limiter_is_singleton(self):
        a = get_endpoint_rate_limiter()
        b = get_endpoint_rate_limiter()
        self.assertIs(a, b)
        self.assertIsInstance(a, EndpointRateLimiter)


if __name__ == "__main__":
    unittest.main()
