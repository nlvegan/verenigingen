"""
Integration coverage (Tier-2) for the Mollie error-recovery engine —
utils/error_recovery.py.

This module is pure orchestration logic (retry with backoff, circuit breaker
state machine, recovery-queue workflows, error classification). It touches the
DB only via frappe.cache() and frappe.log_error(), so it runs with no Mollie
credentials and no mocks of the logic under test. The only injected seam is the
*operation* callable passed in by the caller — exactly the production contract.

Targets (verenigingen/verenigingen_payments/mollie/utils/error_recovery.py):
  MollieErrorRecovery
    - execute_with_retry          (success-first / retry-then-succeed / exhausted /
                                   non-retryable short-circuit)
    - execute_with_circuit_breaker (success / failure-opens / open-rejects /
                                    half-open recovery close)
    - create_recovery_workflow + process_recovery_queue + get_error_recovery_status
    - _should_retry_error / _classify_error_severity / _calculate_retry_delay
    - _is_circuit_open recovery-timeout transition
  decorators with_retry / with_circuit_breaker

We instantiate a *fresh* MollieErrorRecovery per test (not the module-global
singleton) so circuit-breaker / queue state is isolated and deterministic, and we
shrink RetryConfig base_delay so the real time.sleep stays sub-millisecond.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.exceptions import (
    MolliePaymentError,
    MollieSecurityError,
    MollieWebhookError,
)
from verenigingen.verenigingen_payments.mollie.utils.error_recovery import (
    CircuitBreakerConfig,
    CircuitBreakerState,
    ErrorSeverity,
    MollieErrorRecovery,
    RetryConfig,
    RetryStrategy,
    with_circuit_breaker,
    with_retry,
)


def _fast_retry(max_attempts=3):
    """RetryConfig with negligible delay so sleeps don't slow the suite."""
    return RetryConfig(max_attempts=max_attempts, base_delay=0.0, max_delay=0.0, jitter=False)


class TestExecuteWithRetry(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.recovery = MollieErrorRecovery()

    def test_success_on_first_attempt(self):
        calls = []

        def op():
            calls.append(1)
            return "ok"

        result = self.recovery.execute_with_retry(op, "first_try", _fast_retry())
        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1, "should not retry a successful op")

    def test_succeeds_after_transient_failures(self):
        state = {"n": 0}

        def op():
            state["n"] += 1
            if state["n"] < 3:
                raise ConnectionError("transient")
            return {"attempts": state["n"]}

        result = self.recovery.execute_with_retry(op, "eventual", _fast_retry(max_attempts=3))
        self.assertEqual(result, {"attempts": 3})
        # Recovery-success metric recorded in cache
        cached = frappe.cache().get("mollie_recovery_success:eventual")
        self.assertIsNotNone(cached, "recovery success should be recorded in cache")

    def test_exhausts_attempts_and_raises_payment_error(self):
        state = {"n": 0}

        def op():
            state["n"] += 1
            raise ConnectionError("always fails")

        with self.assertRaises(MolliePaymentError):
            self.recovery.execute_with_retry(op, "always_fail", _fast_retry(max_attempts=3))
        self.assertEqual(state["n"], 3, "should attempt exactly max_attempts times")
        # Operation-failure metric recorded
        self.assertIsNotNone(frappe.cache().get("mollie_operation_failure:always_fail"))

    def test_non_retryable_error_short_circuits(self):
        state = {"n": 0}

        def op():
            state["n"] += 1
            raise MollieSecurityError("nope")

        with self.assertRaises(MolliePaymentError):
            self.recovery.execute_with_retry(op, "security_fail", _fast_retry(max_attempts=5))
        # Security errors are non-retryable: exactly one attempt, no looping
        self.assertEqual(state["n"], 1, "non-retryable error must not be retried")


class TestShouldRetryAndClassify(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.recovery = MollieErrorRecovery()

    def test_security_and_webhook_not_retryable(self):
        self.assertFalse(self.recovery._should_retry_error(MollieSecurityError("x")))
        self.assertFalse(self.recovery._should_retry_error(MollieWebhookError("x")))

    def test_generic_error_retryable(self):
        self.assertTrue(self.recovery._should_retry_error(ConnectionError("x")))
        self.assertTrue(self.recovery._should_retry_error(TimeoutError("x")))

    def test_http_4xx_not_retryable_5xx_retryable(self):
        class FakeResponse:
            def __init__(self, code):
                self.status_code = code

        class HttpError(Exception):
            def __init__(self, code):
                self.response = FakeResponse(code)

        for code in (400, 401, 403, 404):
            self.assertFalse(self.recovery._should_retry_error(HttpError(code)), f"{code} retryable?")
        self.assertTrue(self.recovery._should_retry_error(HttpError(500)))

    def test_severity_classification(self):
        self.assertEqual(
            self.recovery._classify_error_severity(MollieSecurityError("x")), ErrorSeverity.CRITICAL
        )
        self.assertEqual(self.recovery._classify_error_severity(MollieWebhookError("x")), ErrorSeverity.HIGH)
        self.assertEqual(self.recovery._classify_error_severity(ValueError("x")), ErrorSeverity.LOW)

    def test_payment_error_classified_medium_regression(self):
        """Regression: MolliePaymentError is a subclass of MollieWebhookError, so
        the isinstance checks must test the specific subclass first. Before the
        fix the broad MollieWebhookError branch caught it and returned HIGH,
        leaving the intended MEDIUM branch unreachable."""
        self.assertEqual(
            self.recovery._classify_error_severity(MolliePaymentError("x")), ErrorSeverity.MEDIUM
        )
        # And the security subclass (also a MollieWebhookError) stays CRITICAL.
        self.assertEqual(
            self.recovery._classify_error_severity(MollieSecurityError("x")), ErrorSeverity.CRITICAL
        )


class TestRetryDelay(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.recovery = MollieErrorRecovery()

    def test_exponential_backoff(self):
        cfg = RetryConfig(base_delay=1.0, backoff_multiplier=2.0, jitter=False, max_delay=100.0)
        self.assertEqual(self.recovery._calculate_retry_delay(0, cfg), 1.0)
        self.assertEqual(self.recovery._calculate_retry_delay(1, cfg), 2.0)
        self.assertEqual(self.recovery._calculate_retry_delay(2, cfg), 4.0)

    def test_linear_backoff(self):
        cfg = RetryConfig(
            base_delay=2.0, strategy=RetryStrategy.LINEAR_BACKOFF, jitter=False, max_delay=100.0
        )
        self.assertEqual(self.recovery._calculate_retry_delay(0, cfg), 2.0)
        self.assertEqual(self.recovery._calculate_retry_delay(2, cfg), 6.0)

    def test_fixed_interval_and_max_cap(self):
        cfg = RetryConfig(base_delay=5.0, strategy=RetryStrategy.FIXED_INTERVAL, jitter=False, max_delay=3.0)
        # Fixed interval would be 5.0 but is capped to max_delay 3.0
        self.assertEqual(self.recovery._calculate_retry_delay(10, cfg), 3.0)

    def test_jitter_within_bounds(self):
        cfg = RetryConfig(base_delay=10.0, backoff_multiplier=1.0, jitter=True, max_delay=100.0)
        d = self.recovery._calculate_retry_delay(0, cfg)
        # base 10 + up to 10% jitter
        self.assertGreaterEqual(d, 10.0)
        self.assertLessEqual(d, 11.0)


class TestCircuitBreaker(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.recovery = MollieErrorRecovery()

    def test_success_passes_through(self):
        result = self.recovery.execute_with_circuit_breaker(lambda: "ok", "cb_success")
        self.assertEqual(result, "ok")

    def test_failures_open_circuit_then_reject(self):
        cfg = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=60)

        def boom():
            raise ConnectionError("down")

        # Drive failures up to threshold; each raises the original error
        for _ in range(3):
            with self.assertRaises(ConnectionError):
                self.recovery.execute_with_circuit_breaker(boom, "cb_open", cfg)

        state = self.recovery.circuit_breakers["cb_open"]
        self.assertTrue(state.is_open, "circuit should be open after threshold failures")

        # Now a NEW call is rejected by the open circuit (MolliePaymentError), and
        # the underlying operation is NOT invoked.
        invoked = {"n": 0}

        def should_not_run():
            invoked["n"] += 1
            return "x"

        with self.assertRaises(MolliePaymentError):
            self.recovery.execute_with_circuit_breaker(should_not_run, "cb_open", cfg)
        self.assertEqual(invoked["n"], 0, "open circuit must short-circuit the operation")

    def test_half_open_recovery_closes_circuit(self):
        cfg = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0, success_threshold=2)

        # Open the circuit with one failure
        with self.assertRaises(ConnectionError):
            self.recovery.execute_with_circuit_breaker(
                lambda: (_ for _ in ()).throw(ConnectionError("x")), "cb_half", cfg
            )
        state = self.recovery.circuit_breakers["cb_half"]
        self.assertTrue(state.is_open)

        # recovery_timeout=0 -> next check transitions to half-open and allows the op.
        # success_threshold=2 successes are needed to fully close.
        self.recovery.execute_with_circuit_breaker(lambda: "ok1", "cb_half", cfg)
        self.recovery.execute_with_circuit_breaker(lambda: "ok2", "cb_half", cfg)

        state = self.recovery.circuit_breakers["cb_half"]
        self.assertFalse(state.is_open)
        self.assertEqual(state.failure_count, 0, "circuit fully closed -> failures reset")

    def test_is_circuit_open_recovery_timeout_transition(self):
        cfg = CircuitBreakerConfig(recovery_timeout=0)
        state = CircuitBreakerState(is_open=True, last_failure_time=frappe.utils.now_datetime())
        # recovery_timeout=0 means recovery time already elapsed -> half-open
        self.assertFalse(self.recovery._is_circuit_open(state, cfg))
        self.assertFalse(state.is_open)
        self.assertIsNotNone(state.half_open_test_time)


class TestRecoveryWorkflows(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.recovery = MollieErrorRecovery()

    def test_create_workflow_enqueues_and_persists(self):
        # frappe.log_error stores the `title` in the Error Log `method` column.
        wf_id = self.recovery.create_recovery_workflow(
            "unit_wf", {"operation_type": "test", "error_details": {"x": 1}}, "manual_review"
        )
        self.assertTrue(wf_id.startswith("unit_wf_"))
        self.assertIn("unit_wf", self.recovery.recovery_queues)
        self.assertEqual(len(self.recovery.recovery_queues["unit_wf"]), 1)
        item = self.recovery.recovery_queues["unit_wf"][0]
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["strategy"], "manual_review")
        # Persisted to Error Log under the "Mollie Recovery Workflow: unit_wf" title.
        persisted = frappe.get_all(
            "Error Log",
            filters={"method": ("like", "%Mollie Recovery Workflow: unit_wf%")},
            fields=["name", "error"],
            order_by="creation desc",
            limit=1,
        )
        self.assertTrue(persisted, "recovery workflow should be persisted to Error Log")
        # The serialised workflow id is captured in the message body.
        self.assertIn(wf_id, persisted[0].error)

    def test_process_recovery_queue_manual_review_completes(self):
        self.recovery.create_recovery_workflow("unit_mr", {"operation_type": "test"}, "manual_review")
        results = self.recovery.process_recovery_queue("unit_mr", max_items=10)
        self.assertEqual(results["processed"], 1)
        self.assertEqual(results["succeeded"], 1, "manual_review strategy returns success")
        self.assertEqual(self.recovery.recovery_queues["unit_mr"][0]["status"], "completed")

    def test_process_recovery_queue_unknown_strategy_retries_then_fails(self):
        self.recovery.create_recovery_workflow("unit_bad", {"operation_type": "test"}, "no_such_strategy")
        item = self.recovery.recovery_queues["unit_bad"][0]
        item["max_retries"] = 2

        # First pass: unknown strategy -> False -> retry_count=1 -> skipped
        r1 = self.recovery.process_recovery_queue("unit_bad", max_items=10)
        self.assertEqual(r1["skipped"], 1)
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["retry_count"], 1)

        # Second pass: retry_count reaches max_retries -> failed
        r2 = self.recovery.process_recovery_queue("unit_bad", max_items=10)
        self.assertEqual(r2["failed"], 1)
        self.assertEqual(item["status"], "failed")

    def test_process_unknown_queue_returns_zeroes(self):
        out = self.recovery.process_recovery_queue("does_not_exist")
        self.assertEqual(out, {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 0})

    def test_get_status_reports_queues_and_circuits(self):
        # Seed a circuit breaker and a queue
        self.recovery.execute_with_circuit_breaker(lambda: "ok", "status_cb")
        self.recovery.create_recovery_workflow("status_q", {"operation_type": "t"}, "manual_review")

        status = self.recovery.get_error_recovery_status()
        self.assertIn("status_cb", status["circuit_breakers"])
        self.assertIn("status_q", status["recovery_queues"])
        q = status["recovery_queues"]["status_q"]
        self.assertEqual(q["total_items"], 1)
        self.assertEqual(q["pending"], 1)


class TestDecorators(EnhancedTestCase):
    def test_with_retry_decorator_retries(self):
        state = {"n": 0}

        @with_retry(_fast_retry(max_attempts=3))
        def flaky():
            state["n"] += 1
            if state["n"] < 2:
                raise ConnectionError("transient")
            return "done"

        self.assertEqual(flaky(), "done")
        self.assertEqual(state["n"], 2)

    def test_with_circuit_breaker_decorator_passes_through(self):
        @with_circuit_breaker("decorated_cb")
        def ok():
            return 42

        self.assertEqual(ok(), 42)

    def test_with_circuit_breaker_decorator_opens_and_rejects(self):
        """The decorated path must open the circuit after threshold failures and
        then reject subsequent calls with MolliePaymentError (without invoking the
        wrapped function)."""
        cfg = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60)
        circuit = f"dec_open_{frappe.generate_hash()[:8]}"
        runs = {"n": 0}

        @with_circuit_breaker(circuit, cfg)
        def flaky():
            runs["n"] += 1
            raise ConnectionError("down")

        # Two failures open the circuit (original error propagates)
        for _ in range(2):
            with self.assertRaises(ConnectionError):
                flaky()
        self.assertEqual(runs["n"], 2)

        # Now the open circuit rejects without running the body
        with self.assertRaises(MolliePaymentError):
            flaky()
        self.assertEqual(runs["n"], 2, "open circuit must short-circuit the decorated body")


class TestAttemptAutomaticRecovery(EnhancedTestCase):
    """_attempt_automatic_recovery — the webhook_processing branch.

    Regression guard: this path imported a class that no longer exists
    (WebhookWrapperServiceUnified) and called a removed method (process_webhook),
    so it raised ImportError on every invocation. It now uses the real
    UnifiedWebhookWrapperService.process_payment_webhook(payment_id, operation_data).
    """

    def setUp(self):
        super().setUp()
        self.recovery = MollieErrorRecovery()

    def test_webhook_recovery_calls_real_service_and_succeeds(self):
        from unittest.mock import patch

        captured = {}

        class _FakeService:
            def process_payment_webhook(self, payment_id, webhook_data):
                captured["payment_id"] = payment_id
                captured["webhook_data"] = webhook_data
                return {"status": "success"}

        target = (
            "verenigingen.verenigingen_payments.mollie.services."
            "webhook_wrapper_service_unified.UnifiedWebhookWrapperService"
        )
        with patch(target, _FakeService):
            ok = self.recovery._attempt_automatic_recovery(
                {"operation_type": "webhook_processing", "payment_id": "tr_recover_1"}
            )

        self.assertTrue(ok)
        self.assertEqual(captured["payment_id"], "tr_recover_1")
        # The recovery passes its operation_data through as the webhook_data arg.
        self.assertEqual(captured["webhook_data"]["payment_id"], "tr_recover_1")

    def test_webhook_recovery_returns_false_on_non_success(self):
        from unittest.mock import patch

        class _FakeService:
            def process_payment_webhook(self, payment_id, webhook_data):
                return {"status": "error"}

        target = (
            "verenigingen.verenigingen_payments.mollie.services."
            "webhook_wrapper_service_unified.UnifiedWebhookWrapperService"
        )
        with patch(target, _FakeService):
            ok = self.recovery._attempt_automatic_recovery(
                {"operation_type": "webhook_processing", "payment_id": "tr_recover_2"}
            )
        self.assertFalse(ok)

    def test_no_payment_id_returns_false_without_calling_service(self):
        ok = self.recovery._attempt_automatic_recovery({"operation_type": "webhook_processing"})
        self.assertFalse(ok)
