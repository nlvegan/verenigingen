"""
Coverage gap-fill for the Mollie resilience retry policy.

Target: verenigingen/verenigingen_payments/core/resilience/retry_policy.py

This module is PURE logic (error classification, backoff math, retry budget),
so these tests use plain unittest.TestCase -- no database, no Mollie HTTP.
Timing-sensitive paths use freezegun.freeze_time (budget window) or directly
exercise _calculate_delay (no sleep) with jitter disabled for determinism.
Sleep-based retry loops use tiny real windows (base_delay 0.001s).

Run with:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_retry_policy_coverage_b3
"""

import unittest
from datetime import datetime, timedelta

from freezegun import freeze_time

from verenigingen.verenigingen_payments.core.resilience.retry_policy import (
    ExponentialBackoffRetry,
    FibonacciBackoffRetry,
    FixedDelayRetry,
    LinearBackoffRetry,
    RetryStrategy,
    SmartRetryPolicy,
    retry_with_backoff,
)


class TestExponentialBackoffDelay(unittest.TestCase):
    """_calculate_delay math for the exponential strategy (no sleep)."""

    def _policy(self, **kw):
        kw.setdefault("jitter", False)
        kw.setdefault("base_delay", 1.0)
        kw.setdefault("max_delay", 60.0)
        kw.setdefault("exponential_base", 2.0)
        return ExponentialBackoffRetry(**kw)

    def test_exponential_progression(self):
        policy = self._policy()
        # attempt is 1-based: base * base^(attempt-1)
        self.assertEqual(policy._calculate_delay(1), 1.0)
        self.assertEqual(policy._calculate_delay(2), 2.0)
        self.assertEqual(policy._calculate_delay(3), 4.0)
        self.assertEqual(policy._calculate_delay(4), 8.0)

    def test_delay_capped_at_max_delay(self):
        policy = self._policy(max_delay=5.0)
        # 2^4 = 16 but capped to 5
        self.assertEqual(policy._calculate_delay(5), 5.0)

    def test_jitter_multiplies_within_range(self):
        policy = ExponentialBackoffRetry(
            base_delay=10.0, exponential_base=1.0, jitter=True, jitter_range=(0.5, 1.5)
        )
        for _ in range(50):
            delay = policy._calculate_delay(1)
            # base stays 10 (exp_base 1.0); jitter scales it into [5, 15]
            self.assertGreaterEqual(delay, 5.0)
            self.assertLessEqual(delay, 15.0)


class TestLinearBackoffDelay(unittest.TestCase):
    def test_linear_progression(self):
        policy = LinearBackoffRetry(base_delay=2.0, max_delay=100.0, jitter=False)
        self.assertEqual(policy._calculate_delay(1), 2.0)
        self.assertEqual(policy._calculate_delay(2), 4.0)
        self.assertEqual(policy._calculate_delay(3), 6.0)

    def test_linear_capped(self):
        policy = LinearBackoffRetry(base_delay=2.0, max_delay=5.0, jitter=False)
        self.assertEqual(policy._calculate_delay(10), 5.0)


class TestFixedDelay(unittest.TestCase):
    def test_fixed_is_constant(self):
        policy = FixedDelayRetry(base_delay=3.0, jitter=False)
        self.assertEqual(policy._calculate_delay(1), 3.0)
        self.assertEqual(policy._calculate_delay(7), 3.0)


class TestFibonacciBackoffDelay(unittest.TestCase):
    def test_fibonacci_sequence(self):
        policy = FibonacciBackoffRetry(base_delay=1.0, max_delay=1000.0, jitter=False)
        # fib_sequence seeded [1, 1]; delay = base * fib[attempt-1]
        self.assertEqual(policy._calculate_delay(1), 1.0)  # fib[0] = 1
        self.assertEqual(policy._calculate_delay(2), 1.0)  # fib[1] = 1
        self.assertEqual(policy._calculate_delay(3), 2.0)  # fib[2] = 2
        self.assertEqual(policy._calculate_delay(4), 3.0)  # fib[3] = 3
        self.assertEqual(policy._calculate_delay(5), 5.0)  # fib[4] = 5
        self.assertEqual(policy._calculate_delay(6), 8.0)  # fib[5] = 8

    def test_fibonacci_capped(self):
        policy = FibonacciBackoffRetry(base_delay=1.0, max_delay=4.0, jitter=False)
        # fib grows past max_delay -> capped
        self.assertEqual(policy._calculate_delay(8), 4.0)


class TestExponentialExecute(unittest.TestCase):
    """execute() retry loop -- success after retries, exhaustion, metrics."""

    def _fast_policy(self, max_attempts=3):
        # tiny real backoff window; jitter off for determinism
        return ExponentialBackoffRetry(
            max_attempts=max_attempts, base_delay=0.001, max_delay=0.002, jitter=False
        )

    def test_success_first_try_no_retry_metrics(self):
        policy = self._fast_policy()
        result = policy.execute(lambda: "ok")
        self.assertEqual(result, "ok")
        self.assertEqual(policy.successful_retries, 0)
        self.assertEqual(policy.failed_retries, 0)
        self.assertEqual(policy.total_attempts, 1)

    def test_success_after_retries(self):
        policy = self._fast_policy(max_attempts=5)
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("boom")
            return "recovered"

        self.assertEqual(policy.execute(flaky), "recovered")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(policy.successful_retries, 1)
        self.assertEqual(policy.failed_retries, 0)

    def test_all_retries_exhausted_raises_last(self):
        policy = self._fast_policy(max_attempts=3)

        def always_fail():
            raise ValueError("nope")

        with self.assertRaises(ValueError):
            policy.execute(always_fail)
        self.assertEqual(policy.failed_retries, 1)
        self.assertEqual(policy.total_attempts, 3)

    def test_get_metrics_shape_and_rate(self):
        policy = self._fast_policy(max_attempts=4)
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise TimeoutError("slow")
            return "ok"

        policy.execute(flaky)
        metrics = policy.get_metrics()
        self.assertEqual(metrics["max_attempts"], 4)
        self.assertEqual(metrics["successful_retries"], 1)
        self.assertEqual(metrics["failed_retries"], 0)
        self.assertEqual(metrics["retry_success_rate"], 1.0)
        self.assertGreaterEqual(metrics["total_delay_time"], 0.0)

    def test_get_metrics_zero_division_safe(self):
        # No retries attempted -> rate/average return 0, not ZeroDivisionError
        policy = self._fast_policy()
        metrics = policy.get_metrics()
        self.assertEqual(metrics["retry_success_rate"], 0)
        self.assertEqual(metrics["average_delay"], 0)


class TestSmartRetryClassification(unittest.TestCase):
    """should_retry() error classification (the main gap)."""

    def setUp(self):
        self.policy = SmartRetryPolicy(retry_budget=100)

    def test_connection_error_is_retryable(self):
        should, config = self.policy.should_retry(ConnectionError("net down"))
        self.assertTrue(should)
        self.assertEqual(config["strategy"], RetryStrategy.EXPONENTIAL)
        self.assertEqual(config["max_attempts"], 5)

    def test_timeout_error_is_retryable(self):
        should, config = self.policy.should_retry(TimeoutError("slow"))
        self.assertTrue(should)
        self.assertEqual(config["max_attempts"], 3)

    def test_string_classified_rate_limit_error(self):
        # Classification by type-name string (no real exception class needed).
        class RateLimitError(Exception):
            pass

        should, config = self.policy.should_retry(RateLimitError("429"))
        self.assertTrue(should)
        self.assertEqual(config["base_delay"], 5)

    def test_non_retryable_by_name(self):
        class AuthenticationError(Exception):
            pass

        should, config = self.policy.should_retry(AuthenticationError("bad key"))
        self.assertFalse(should)
        self.assertIsNone(config)

    def test_unknown_error_not_retried(self):
        should, config = self.policy.should_retry(RuntimeError("mystery"))
        self.assertFalse(should)
        self.assertIsNone(config)

    def test_permission_error_not_retried(self):
        # PermissionError name is in the non-retryable list
        should, _ = self.policy.should_retry(PermissionError("denied"))
        self.assertFalse(should)


class TestSmartRetryBudget(unittest.TestCase):
    def test_budget_exhaustion_blocks_retry(self):
        policy = SmartRetryPolicy(retry_budget=1)
        # Drain the budget below the reset window
        policy.remaining_budget = 0
        should, config = policy.should_retry(ConnectionError("net"))
        self.assertFalse(should)
        self.assertIsNone(config)

    def test_consume_budget_decrements_and_floors_at_zero(self):
        policy = SmartRetryPolicy(retry_budget=2)
        policy._consume_budget()
        self.assertEqual(policy.remaining_budget, 1)
        policy._consume_budget()
        policy._consume_budget()  # would go negative; floored at 0
        self.assertEqual(policy.remaining_budget, 0)

    def test_budget_resets_after_window(self):
        # Start frozen; exhaust budget; advance past reset time -> refilled.
        with freeze_time("2026-01-01 12:00:00") as frozen:
            policy = SmartRetryPolicy(retry_budget=5)
            policy.remaining_budget = 0
            self.assertFalse(policy._check_budget())
            # advance beyond the 1-minute window
            frozen.tick(delta=timedelta(seconds=61))
            self.assertTrue(policy._check_budget())
            self.assertEqual(policy.remaining_budget, 5)


class TestSmartRetryExecuteWithClassification(unittest.TestCase):
    def setUp(self):
        self.policy = SmartRetryPolicy(retry_budget=100)
        # Make the underlying strategies effectively instant.
        for strat in self.policy.strategies.values():
            strat.base_delay = 0.001
            strat.max_delay = 0.002
            strat.jitter = False

    def test_success_resets_error_tracking(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ConnectionError("net")
            return "ok"

        result = self.policy.execute_with_classification(flaky)
        self.assertEqual(result, "ok")
        self.assertEqual(self.policy.consecutive_errors.get("flaky"), 0)

    def test_non_retryable_reraises_immediately(self):
        class InvalidRequestError(Exception):
            pass

        def bad():
            raise InvalidRequestError("400")

        with self.assertRaises(InvalidRequestError):
            self.policy.execute_with_classification(bad)

    def test_exhausts_max_attempts_then_reraises(self):
        def always_timeout():
            raise TimeoutError("slow")  # max_attempts=3 in config

        with self.assertRaises(TimeoutError):
            self.policy.execute_with_classification(always_timeout)
        # error pattern tracking should have recorded the func/error key
        patterns = self.policy.get_error_patterns()
        self.assertTrue(any("always_timeout:TimeoutError" in k for k in patterns))
        self.assertEqual(patterns["always_timeout:TimeoutError"]["count"], 3)

    def test_error_pattern_tracking_counts(self):
        def fail():
            raise ConnectionError("x")  # retryable, max_attempts=5

        with self.assertRaises(ConnectionError):
            self.policy.execute_with_classification(fail)
        patterns = self.policy.get_error_patterns()
        key = "fail:ConnectionError"
        self.assertIn(key, patterns)
        self.assertEqual(patterns[key]["count"], 5)
        self.assertIsNotNone(patterns[key]["last_seen"])


class TestRetryWithBackoffDecorator(unittest.TestCase):
    def test_decorator_returns_on_success(self):
        @retry_with_backoff(max_attempts=3, base_delay=0.001, max_delay=0.002)
        def ok():
            return 42

        self.assertEqual(ok(), 42)

    def test_decorator_retries_then_succeeds(self):
        state = {"n": 0}

        @retry_with_backoff(
            max_attempts=4, base_delay=0.001, max_delay=0.002, exceptions=(ConnectionError,)
        )
        def flaky():
            state["n"] += 1
            if state["n"] < 3:
                raise ConnectionError("net")
            return "done"

        self.assertEqual(flaky(), "done")
        self.assertEqual(state["n"], 3)

    def test_decorator_raises_after_exhaustion(self):
        @retry_with_backoff(max_attempts=2, base_delay=0.001, max_delay=0.002, exceptions=(ValueError,))
        def bad():
            raise ValueError("always")

        with self.assertRaises(ValueError):
            bad()

    def test_decorator_does_not_catch_unlisted_exception(self):
        @retry_with_backoff(max_attempts=3, base_delay=0.001, exceptions=(ConnectionError,))
        def boom():
            raise KeyError("not caught")

        with self.assertRaises(KeyError):
            boom()


if __name__ == "__main__":
    unittest.main()
