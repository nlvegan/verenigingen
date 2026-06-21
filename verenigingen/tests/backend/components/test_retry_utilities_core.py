"""
Tests for the core (non-deadlock) retry utilities in retry_utilities.py.

Covers the general-purpose helpers that the existing
test_deadlock_retry_utilities.py suite does NOT exercise:
- classify_error()
- exponential_backoff_with_jitter()
- retry_with_backoff() decorator
- RetryContext iterator + should_retry()
- retry_operation()

These tests drive the real retry/backoff machinery with deterministic
failing-then-succeeding callables passed as arguments (no business-logic
mocking). time.sleep is patched only to keep the suite fast; the retry
control flow itself is exercised for real.
"""

import unittest
from unittest.mock import patch

import frappe

from verenigingen.utils.retry_utilities import (
    ErrorCategory,
    RetryContext,
    classify_error,
    exponential_backoff_with_jitter,
    retry_operation,
    retry_with_backoff,
)


class _FlakyCallable:
    """Deterministic callable: raises `exc` for the first `fail_times` calls,
    then returns `result`. Records the number of invocations."""

    def __init__(self, fail_times, exc, result="ok"):
        self.fail_times = fail_times
        self.exc = exc
        self.result = result
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.result


class TestClassifyError(unittest.TestCase):
    def test_transient_indicators(self):
        for msg in [
            "Broken pipe",
            "Connection reset by peer",
            "connection refused",
            "Operation timeout",
            "Timestamp mismatch detected",
            "Lock wait timeout exceeded",
            "Deadlock found",
            "Too many connections",
        ]:
            self.assertEqual(
                classify_error(Exception(msg)),
                ErrorCategory.TRANSIENT,
                msg=f"{msg!r} should be TRANSIENT",
            )

    def test_permanent_indicators(self):
        for msg in [
            "Permission denied",
            "Table does not exist",
            "Validation error: field required",
            "Duplicate entry '1' for key",
            "Cannot add or update a child row: a foreign key constraint fails",
            "Record not found",
        ]:
            self.assertEqual(
                classify_error(Exception(msg)),
                ErrorCategory.PERMANENT,
                msg=f"{msg!r} should be PERMANENT",
            )

    def test_unknown_when_no_indicator_matches(self):
        self.assertEqual(
            classify_error(Exception("some entirely novel failure mode")),
            ErrorCategory.UNKNOWN,
        )

    def test_transient_takes_precedence_over_permanent(self):
        # A message containing both a transient and a permanent indicator
        # is classified TRANSIENT because transient indicators are checked first.
        err = Exception("deadlock; record not found")
        self.assertEqual(classify_error(err), ErrorCategory.TRANSIENT)


class TestExponentialBackoff(unittest.TestCase):
    def test_no_jitter_is_pure_exponential(self):
        # jitter_factor=0 removes randomness so the formula is deterministic.
        self.assertAlmostEqual(
            exponential_backoff_with_jitter(0, base_delay=0.1, jitter_factor=0.0), 0.1
        )
        self.assertAlmostEqual(
            exponential_backoff_with_jitter(1, base_delay=0.1, jitter_factor=0.0), 0.2
        )
        self.assertAlmostEqual(
            exponential_backoff_with_jitter(3, base_delay=0.1, jitter_factor=0.0), 0.8
        )

    def test_capped_at_max_delay(self):
        # 0.1 * 2**20 is huge; must be capped at max_delay (no jitter).
        self.assertAlmostEqual(
            exponential_backoff_with_jitter(20, base_delay=0.1, max_delay=2.0, jitter_factor=0.0),
            2.0,
        )

    def test_never_negative_even_with_max_jitter(self):
        # With jitter_factor=1.0 the jitter can be as low as -delay; result clamps at 0.
        for attempt in range(6):
            for _ in range(20):
                d = exponential_backoff_with_jitter(
                    attempt, base_delay=0.1, max_delay=10.0, jitter_factor=1.0
                )
                self.assertGreaterEqual(d, 0.0)

    def test_jitter_stays_within_band(self):
        # Delay must remain within [delay - jitter*delay, delay + jitter*delay], clamped >= 0.
        base = 0.5
        for _ in range(50):
            d = exponential_backoff_with_jitter(0, base_delay=base, jitter_factor=0.5)
            self.assertGreaterEqual(d, 0.0)
            self.assertLessEqual(d, base * 1.5 + 1e-9)


class TestRetryWithBackoffDecorator(unittest.TestCase):
    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_succeeds_after_transient_failures(self, _sleep):
        flaky = _FlakyCallable(fail_times=2, exc=Exception("connection reset"), result=42)

        @retry_with_backoff(max_retries=3, base_delay=0.01)
        def op():
            return flaky()

        self.assertEqual(op(), 42)
        # 2 failures + 1 success
        self.assertEqual(flaky.calls, 3)

    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_raises_after_exhausting_retries(self, _sleep):
        flaky = _FlakyCallable(fail_times=99, exc=Exception("timeout"))

        @retry_with_backoff(max_retries=2, base_delay=0.01)
        def op():
            return flaky()

        with self.assertRaises(Exception):
            op()
        # initial attempt + 2 retries = 3 invocations
        self.assertEqual(flaky.calls, 3)

    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_permanent_error_is_retried_when_no_retry_on_filter(self, _sleep):
        # When retry_on is None, the `if retry_on and not isinstance(...)` guard
        # is False, so classify_error() is never consulted -> ALL errors are
        # retried up to max_retries regardless of classification. This documents
        # the decorator's actual (filter-less) behavior; the PERMANENT fail-fast
        # path only engages when retry_on IS supplied (see the test below).
        flaky = _FlakyCallable(fail_times=99, exc=Exception("Duplicate entry detected"))

        @retry_with_backoff(max_retries=2, base_delay=0.01)
        def op():
            return flaky()

        with self.assertRaises(Exception):
            op()
        # initial attempt + 2 retries = 3 invocations
        self.assertEqual(flaky.calls, 3)

    def test_skip_on_takes_precedence(self):
        flaky = _FlakyCallable(fail_times=99, exc=ValueError("boom"))

        @retry_with_backoff(max_retries=5, base_delay=0.01, skip_on=(ValueError,))
        def op():
            return flaky()

        with self.assertRaises(ValueError):
            op()
        self.assertEqual(flaky.calls, 1)

    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_retry_on_whitelist_retries_listed_type(self, _sleep):
        flaky = _FlakyCallable(fail_times=1, exc=KeyError("k"), result="done")

        @retry_with_backoff(max_retries=3, base_delay=0.01, retry_on=(KeyError,))
        def op():
            return flaky()

        self.assertEqual(op(), "done")
        self.assertEqual(flaky.calls, 2)

    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_retry_on_whitelist_with_permanent_unlisted_error_fails_fast(self, _sleep):
        # Error is not in retry_on AND classifies PERMANENT -> raise immediately.
        flaky = _FlakyCallable(fail_times=99, exc=Exception("permission denied"))

        @retry_with_backoff(max_retries=3, base_delay=0.01, retry_on=(KeyError,))
        def op():
            return flaky()

        with self.assertRaises(Exception):
            op()
        self.assertEqual(flaky.calls, 1)

    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_on_retry_callback_invoked_with_attempt_and_delay(self, _sleep):
        flaky = _FlakyCallable(fail_times=2, exc=Exception("timeout"), result="ok")
        seen = []

        def on_retry(exc, attempt, delay):
            seen.append((str(exc), attempt, delay))

        @retry_with_backoff(max_retries=3, base_delay=0.01, on_retry=on_retry)
        def op():
            return flaky()

        self.assertEqual(op(), "ok")
        # Two retries -> callback fired twice, attempts 0 and 1.
        self.assertEqual([s[1] for s in seen], [0, 1])
        for _, _, delay in seen:
            self.assertGreaterEqual(delay, 0.0)

    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_no_retry_when_first_call_succeeds(self, _sleep):
        flaky = _FlakyCallable(fail_times=0, exc=Exception("never"), result="immediate")

        @retry_with_backoff(max_retries=3)
        def op():
            return flaky()

        self.assertEqual(op(), "immediate")
        self.assertEqual(flaky.calls, 1)


class TestRetryContext(unittest.TestCase):
    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_iterates_max_retries_plus_one_attempts(self, _sleep):
        ctx = RetryContext(max_retries=3, base_delay=0.01)
        attempts = list(ctx)
        # attempts 0..3 inclusive -> 4 yields
        self.assertEqual(attempts, [0, 1, 2, 3])

    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_sleeps_only_before_retry_attempts(self, sleep_mock):
        ctx = RetryContext(max_retries=2, base_delay=0.01)
        list(ctx)
        # No sleep before attempt 0; sleeps before attempts 1 and 2.
        self.assertEqual(sleep_mock.call_count, 2)

    def test_should_retry_false_for_permanent(self):
        ctx = RetryContext(max_retries=3)
        self.assertFalse(ctx.should_retry(Exception("validation error")))

    def test_should_retry_true_for_transient(self):
        ctx = RetryContext(max_retries=3)
        self.assertTrue(ctx.should_retry(Exception("deadlock found")))

    def test_should_retry_true_for_unknown(self):
        ctx = RetryContext(max_retries=3)
        self.assertTrue(ctx.should_retry(Exception("mysterious failure")))

    def test_should_retry_false_when_attempts_exhausted(self):
        ctx = RetryContext(max_retries=1)
        # Drive the iterator past max so current_attempt > max_retries.
        with patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None):
            list(ctx)
        self.assertFalse(ctx.should_retry(Exception("deadlock found")))


class TestRetryOperation(unittest.TestCase):
    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_returns_result_after_transient_failures(self, _sleep):
        flaky = _FlakyCallable(fail_times=2, exc=Exception("lock wait timeout"), result="value")
        result = retry_operation(flaky, operation_name="flaky-op", max_retries=3, base_delay=0.01)
        self.assertEqual(result, "value")
        self.assertEqual(flaky.calls, 3)

    def test_permanent_error_raises_immediately(self):
        flaky = _FlakyCallable(fail_times=99, exc=Exception("permission denied"))
        with self.assertRaises(Exception):
            retry_operation(flaky, max_retries=5, base_delay=0.01, log_errors=False)
        self.assertEqual(flaky.calls, 1)

    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_raises_last_exception_after_exhaustion(self, _sleep):
        sentinel = Exception("timeout - attempt N")
        flaky = _FlakyCallable(fail_times=99, exc=sentinel)
        with self.assertRaises(Exception) as cm:
            retry_operation(flaky, max_retries=2, base_delay=0.01, log_errors=False)
        self.assertIs(cm.exception, sentinel)
        # initial + 2 retries
        self.assertEqual(flaky.calls, 3)

    @patch("verenigingen.utils.retry_utilities.time.sleep", return_value=None)
    def test_success_on_first_attempt_no_retry(self, _sleep):
        flaky = _FlakyCallable(fail_times=0, exc=Exception("x"), result="first")
        result = retry_operation(flaky, max_retries=3, base_delay=0.01)
        self.assertEqual(result, "first")
        self.assertEqual(flaky.calls, 1)


if __name__ == "__main__":
    unittest.main()
