# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
#1919: no retry wrapper may retry an RQ job timeout.

RQ raises ``JobTimeoutException`` once (SIGALRM). It is an ``Exception`` subclass, so a
retry loop with ``except Exception`` swallowed it and the job ran past its timeout.

Each wrapper is driven with REAL exceptions and a real function; the only patched
boundary is ``time.sleep``, so a retry is observable as a sleep and a second attempt.
The control in each class proves the same wrapper still retries an ordinary transient
error (so "never retried" is not satisfied by "never retries anything").
"""

from unittest.mock import patch

from rq.timeouts import HorseMonitorTimeoutException, JobTimeoutException

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _chained_timeout():
    """Explicit ``raise ... from``: sets BOTH ``__cause__`` and ``__context__``."""
    try:
        try:
            raise JobTimeoutException("Task exceeded maximum timeout value (180 seconds)")
        except JobTimeoutException as timeout:
            raise RuntimeError("API call failed") from timeout
    except RuntimeError as wrapped:
        return wrapped


def _implicitly_chained_timeout(wrapper_type=RuntimeError, message="API call failed"):
    """The Ponto client shape (#1924): raised inside ``except``, no ``from``.

    Sets ``__context__`` ONLY (``__cause__`` is None), so a cause-only walk misses it.
    """
    try:
        try:
            raise JobTimeoutException("Task exceeded maximum timeout value (180 seconds)")
        except JobTimeoutException:
            raise wrapper_type(message)
    except wrapper_type as wrapped:
        return wrapped


class _Flaky:
    """Raises ``first`` on attempt 1, then returns "ok"."""

    def __init__(self, first):
        self.first = first
        self.attempts = 0

    def __call__(self):
        self.attempts += 1
        if self.attempts == 1:
            raise self.first
        return "ok"


class _Mixin:
    """Shared assertions; subclasses provide ``wrap(func)`` and ``transient()``."""

    def _drive(self, first):
        flaky = _Flaky(first)
        flaky.__name__ = "flaky"
        with patch("time.sleep") as sleep:
            try:
                result = self.wrap(flaky)()
                error = None
            except Exception as e:
                result, error = None, e
        return flaky, sleep, result, error

    def test_job_timeout_propagates_on_first_attempt(self):
        for exc in (JobTimeoutException("t"), HorseMonitorTimeoutException("t")):
            flaky, sleep, _, error = self._drive(exc)
            self.assertIs(error, exc)
            self.assertEqual(flaky.attempts, 1)
            sleep.assert_not_called()

    def test_timeout_hidden_in_cause_chain_propagates(self):
        for wrapped in (_chained_timeout(), _implicitly_chained_timeout()):
            flaky, sleep, _, error = self._drive(wrapped)
            self.assertIs(error, wrapped)
            self.assertEqual(flaky.attempts, 1)
            sleep.assert_not_called()

    def test_control_transient_error_is_still_retried(self):
        flaky, sleep, result, error = self._drive(self.transient())
        self.assertIsNone(error)
        self.assertEqual(result, "ok")
        self.assertEqual(flaky.attempts, 2)
        sleep.assert_called_once()


class TestCoreResilienceWithRetry(_Mixin, EnhancedTestCase):
    def wrap(self, func):
        from verenigingen.verenigingen_payments.core.resilience import RetryConfig, with_retry

        return with_retry(RetryConfig(max_attempts=3, base_delay=0.01))(func)

    def transient(self):
        return ConnectionError("reset")


class TestCoreRetryWithBackoffDecorator(_Mixin, EnhancedTestCase):
    def wrap(self, func):
        from verenigingen.verenigingen_payments.core.resilience.retry_policy import retry_with_backoff

        return retry_with_backoff(max_attempts=3, base_delay=0.01)(func)

    def transient(self):
        return ConnectionError("reset")


class TestCoreExecuteAsync(EnhancedTestCase):
    def test_job_timeout_propagates_on_first_attempt(self):
        import asyncio

        from verenigingen.verenigingen_payments.core.resilience.retry_policy import ExponentialBackoffRetry

        attempts = []

        async def boom():
            attempts.append(1)
            raise JobTimeoutException("t")

        policy = ExponentialBackoffRetry(max_attempts=3, base_delay=0.01)
        with patch("asyncio.sleep") as sleep:
            with self.assertRaises(JobTimeoutException):
                asyncio.run(policy.execute_async(boom))
        self.assertEqual(len(attempts), 1)
        sleep.assert_not_called()


class TestSepaWithRetry(_Mixin, EnhancedTestCase):
    def wrap(self, func):
        from verenigingen.verenigingen_payments.utils.sepa_retry_manager import RetryConfig, with_retry

        return with_retry(RetryConfig(max_attempts=3, base_delay=0.01, circuit_breaker_threshold=0))(func)

    def transient(self):
        # "temporary" is a TRANSIENT keyword in SEPARetryManager._classify_failure
        return RuntimeError("temporary glitch")

    def test_timeout_message_would_classify_as_transient(self):
        """Why SEPA needed the guard: RQ's message contains the word 'timeout'."""
        from verenigingen.verenigingen_payments.utils.sepa_retry_manager import FailureType, SEPARetryManager

        kind = SEPARetryManager()._classify_failure(JobTimeoutException("Task exceeded maximum timeout"))
        self.assertEqual(kind, FailureType.TRANSIENT)


class TestMollieWithRetry(_Mixin, EnhancedTestCase):
    def wrap(self, func):
        from verenigingen.verenigingen_payments.mollie.utils.error_recovery import RetryConfig, with_retry

        return with_retry(RetryConfig(max_attempts=3, base_delay=0.01))(func)

    def transient(self):
        return RuntimeError("temporary glitch")

    def test_control_transient_error_is_still_retried(self):
        # The wrapper writes an Error Log row for the failed first attempt.
        self.expectErrorLog("temporary glitch")
        super().test_control_transient_error_is_still_retried()


class TestMigrationWithRetry(_Mixin, EnhancedTestCase):
    def wrap(self, func):
        from verenigingen.utils.migration.migration_error_recovery import RetryStrategy, with_retry

        return with_retry(RetryStrategy(max_retries=3, initial_delay=0.01))(func)

    def transient(self):
        return RuntimeError("temporary glitch")


class TestRetryUtilitiesBackoff(_Mixin, EnhancedTestCase):
    def wrap(self, func):
        from verenigingen.utils.retry_utilities import retry_with_backoff

        return retry_with_backoff(max_retries=3, base_delay=0.01)(func)

    def transient(self):
        return ConnectionError("connection reset by peer")


class TestRetryUtilitiesOperation(_Mixin, EnhancedTestCase):
    def wrap(self, func):
        from verenigingen.utils.retry_utilities import retry_operation

        return lambda: retry_operation(func, "probe", max_retries=3, base_delay=0.01, log_errors=False)

    def transient(self):
        return ConnectionError("connection reset by peer")


class TestSepaErrorHandlerExecuteWithRetry(_Mixin, EnhancedTestCase):
    """``SEPAErrorHandler.execute_with_retry`` returns a result dict instead of raising."""

    def wrap(self, func):
        from verenigingen.verenigingen_payments.utils.sepa_error_handler import SEPAErrorHandler

        handler = SEPAErrorHandler()
        return lambda: handler.execute_with_retry(func)["result"]

    def transient(self):
        return ConnectionError("connection reset by peer")

    def test_control_transient_error_is_still_retried(self):
        self.expectErrorLog("connection reset by peer")
        super().test_control_transient_error_is_still_retried()


class TestSepaRetryDecorator(_Mixin, EnhancedTestCase):
    """``@sepa_retry`` goes through the module-level handler singleton."""

    def wrap(self, func):
        from verenigingen.verenigingen_payments.utils import sepa_error_handler as module

        patcher = patch.object(module, "_error_handler", module.SEPAErrorHandler())  # Mock justified: fresh singleton per test
        patcher.start()
        self.addCleanup(patcher.stop)
        return module.sepa_retry("probe")(func)

    def transient(self):
        return ConnectionError("connection reset by peer")

    def test_control_transient_error_is_still_retried(self):
        self.expectErrorLog("connection reset by peer")
        super().test_control_transient_error_is_still_retried()


class TestSmartRetryPolicyExecuteWithClassification(EnhancedTestCase):
    """Used by ``ResilientHTTPClient``. A bare JobTimeoutException is already
    non-retryable by classification; a RETRYABLE error raised while handling one
    (``ConnectionError`` is in ``retryable_errors``) is what the guard catches."""

    def _run(self, first):
        from verenigingen.verenigingen_payments.core.resilience.retry_policy import SmartRetryPolicy

        flaky = _Flaky(first)
        flaky.__name__ = "flaky"
        with patch("time.sleep") as sleep:
            try:
                result, error = SmartRetryPolicy().execute_with_classification(flaky), None
            except Exception as e:
                result, error = None, e
        return flaky, sleep, result, error

    def test_retryable_error_wrapping_a_timeout_is_not_retried(self):
        wrapped = _implicitly_chained_timeout(ConnectionError, "connection reset")
        flaky, sleep, _, error = self._run(wrapped)
        self.assertIs(error, wrapped)
        self.assertEqual(flaky.attempts, 1)
        sleep.assert_not_called()

    def test_control_plain_connection_error_is_retried(self):
        flaky, sleep, result, error = self._run(ConnectionError("connection reset"))
        self.assertIsNone(error)
        self.assertEqual(result, "ok")
        self.assertEqual(flaky.attempts, 2)


class TestRetryContextShouldRetry(EnhancedTestCase):
    """The documented caller pattern: ``for attempt in ctx`` + ``ctx.should_retry(e)``."""

    def _loop(self, first):
        from verenigingen.utils.retry_utilities import RetryContext

        flaky = _Flaky(first)
        ctx = RetryContext(max_retries=3, base_delay=0.01)
        with patch("time.sleep"):
            for _ in ctx:
                try:
                    return flaky, flaky(), None
                except Exception as e:
                    if ctx.should_retry(e):
                        continue
                    return flaky, None, e
        return flaky, None, None

    def test_job_timeout_is_not_retried(self):
        timeout = JobTimeoutException("Task exceeded maximum timeout value (180 seconds)")
        flaky, _, error = self._loop(timeout)
        self.assertIs(error, timeout)
        self.assertEqual(flaky.attempts, 1)

    def test_control_transient_error_is_retried(self):
        flaky, result, error = self._loop(ConnectionError("connection reset by peer"))
        self.assertIsNone(error)
        self.assertEqual(result, "ok")
        self.assertEqual(flaky.attempts, 2)
