# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for verenigingen_payments.utils.sepa_error_handler.

Covers the error classification table, retry-decision logic, exponential
backoff delay math, the circuit-breaker state machine, execute_with_retry
orchestration, retry-batch creation, the @sepa_retry decorator and the
whitelisted status/reset/create APIs.

Error inputs are REAL exceptions (built with messages that exercise each
classification keyword); no business logic is mocked. The only stubbed
boundary is time.sleep (so retry tests do not actually block) and, in a
couple of places, datetime/now so the circuit-breaker recovery timeout can
be exercised deterministically.
"""

import unittest
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils import sepa_error_handler as seh
from verenigingen.verenigingen_payments.utils.sepa_error_handler import (
    SEPAErrorHandler,
    get_sepa_error_handler,
    sepa_retry,
)


class TestCategorizeError(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.handler = SEPAErrorHandler()

    def test_temporary_keywords(self):
        for msg in ["Connection refused", "Request timeout", "server busy", "network unavailable"]:
            self.assertEqual(self.handler.categorize_error(Exception(msg)), "temporary", msg)

    def test_validation_keywords(self):
        for msg in ["Invalid mandate", "Missing field", "format error", "duplicate entry"]:
            self.assertEqual(self.handler.categorize_error(Exception(msg)), "validation", msg)

    def test_authorization_keywords(self):
        for msg in ["Permission denied", "Unauthorized access", "forbidden", "authentication failed"]:
            self.assertEqual(self.handler.categorize_error(Exception(msg)), "authorization", msg)

    def test_data_keywords(self):
        for msg in ["Record not found", "Member does not exist", "result is empty", "value is null"]:
            self.assertEqual(self.handler.categorize_error(Exception(msg)), "data", msg)

    def test_unknown_when_no_keyword(self):
        self.assertEqual(self.handler.categorize_error(Exception("something weird happened")), "unknown")

    def test_case_insensitive(self):
        self.assertEqual(self.handler.categorize_error(Exception("CONNECTION lost")), "temporary")

    def test_first_matching_category_wins(self):
        # "temporary" is checked before "validation"; a message hitting both
        # returns whichever dict-iteration order encounters first (temporary).
        result = self.handler.categorize_error(Exception("connection invalid"))
        self.assertEqual(result, "temporary")


class TestShouldRetry(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.handler = SEPAErrorHandler()

    def test_stops_at_max_retries(self):
        err = Exception("timeout")
        self.assertFalse(self.handler.should_retry(err, attempt=3))

    def test_retries_temporary_below_max(self):
        self.assertTrue(self.handler.should_retry(Exception("timeout"), attempt=0))
        self.assertTrue(self.handler.should_retry(Exception("timeout"), attempt=2))

    def test_retries_unknown(self):
        self.assertTrue(self.handler.should_retry(Exception("weird"), attempt=0))

    def test_never_retries_validation(self):
        self.assertFalse(self.handler.should_retry(Exception("invalid data"), attempt=0))

    def test_never_retries_data(self):
        self.assertFalse(self.handler.should_retry(Exception("not found"), attempt=0))

    def test_authorization_never_retried(self):
        # Despite the "...unless it's the first attempt" comment at
        # sepa_error_handler.py:85, authorization errors are never retried:
        # the final `return error_category in ["temporary", "unknown"]`
        # (line 90) excludes "authorization" for every attempt, including 0.
        self.assertFalse(self.handler.should_retry(Exception("forbidden"), attempt=0))
        self.assertFalse(self.handler.should_retry(Exception("forbidden"), attempt=1))


class TestCalculateDelay(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.handler = SEPAErrorHandler()

    def test_exponential_growth_with_jitter_bounds(self):
        # base=1, multiplier=2 -> nominal 1,2,4,8 ; jitter adds up to +10%.
        for attempt, nominal in [(0, 1.0), (1, 2.0), (2, 4.0), (3, 8.0)]:
            delay = self.handler.calculate_delay(attempt)
            self.assertGreaterEqual(delay, nominal)
            self.assertLessEqual(delay, nominal * 1.1)

    def test_capped_at_max_delay(self):
        # Large attempt would explode past max_delay (60) before jitter.
        delay = self.handler.calculate_delay(20)
        self.assertGreaterEqual(delay, 60.0)
        self.assertLessEqual(delay, 60.0 * 1.1)


class TestCategorizeErrorParity(EnhancedTestCase):
    """Characterization / parity table pinning categorize_error's exact output.

    These tests pin the CURRENT (pre-refactor) string returned for a
    representative set of inputs, including tricky overlaps that diverge from the
    shared classifier (e.g. "deadlock" / "limit exceeded" are TRANSIENT/RESOURCE
    in the shared classifier but "unknown" here because this method uses a
    NARROWER, keyword-only taxonomy with no isinstance handling). The refactor
    that routes this method through the shared classify_error MUST keep these
    outputs identical.
    """

    # (message, expected_legacy_string)
    PARITY_TABLE = [
        ("connection refused", "temporary"),
        ("request timeout", "temporary"),
        ("server busy", "temporary"),
        ("network unavailable", "temporary"),
        ("lock wait timeout exceeded", "temporary"),
        ("temporary glitch", "temporary"),
        ("resource busy", "temporary"),
        ("resource unavailable", "temporary"),
        ("overload", "temporary"),
        ("connection invalid", "temporary"),  # first-match-wins -> temporary
        # The shared classifier would call these TRANSIENT/RESOURCE, but the
        # legacy keyword set has no "deadlock"/"limit exceeded" -> "unknown".
        ("deadlock detected", "unknown"),
        ("limit exceeded", "unknown"),
        ("something weird happened", "unknown"),
        ("invalid mandate", "validation"),
        ("missing field", "validation"),
        ("format error", "validation"),
        ("duplicate entry", "validation"),
        ("validation failed", "validation"),
        ("required field", "validation"),
        ("constraint violation", "validation"),
        ("permission denied", "authorization"),
        ("unauthorized access", "authorization"),
        ("forbidden", "authorization"),
        ("authentication failed", "authorization"),
        ("record not found", "data"),
        ("does not exist", "data"),
        ("result is empty", "data"),
        ("value is null", "data"),
    ]

    def setUp(self):
        super().setUp()
        self.handler = SEPAErrorHandler()

    def test_keyword_parity_table(self):
        for msg, expected in self.PARITY_TABLE:
            self.assertEqual(
                self.handler.categorize_error(Exception(msg)), expected, msg
            )

    def test_isinstance_errors_have_no_special_handling(self):
        # Legacy categorize_error does NOT inspect exception types; a ValueError
        # / TypeError / PermissionError with a non-keyword message is "unknown".
        self.assertEqual(self.handler.categorize_error(ValueError("x")), "unknown")
        self.assertEqual(self.handler.categorize_error(TypeError("x")), "unknown")
        self.assertEqual(
            self.handler.categorize_error(frappe.PermissionError("x")), "unknown"
        )

    def test_isinstance_does_not_override_keyword(self):
        # A typed exception whose message DOES contain a keyword is still
        # categorized by the keyword (type is irrelevant either way).
        self.assertEqual(self.handler.categorize_error(ValueError("missing thing")), "validation")

    def test_mixed_shared_and_legacy_keywords_return_legacy_category(self):
        """Messages that mix a shared-classifier keyword with a legacy keyword must
        return the LEGACY category, not "unknown".

        The prior refactor delegated to classify_error then applied an override
        layer.  For messages like "invalid deadlock" the shared classifier mapped
        "deadlock" -> TRANSIENT -> "temporary", but the override layer found no
        TEMPORARY legacy keyword in the message and fell back to "unknown".  The
        correct keyword-iteration behavior is: "invalid" matches first under
        "validation" -> return "validation".

        Pinning these four cases as a regression guard.
        """
        cases = [
            # legacy keyword + shared-only keyword -> legacy category wins
            ("invalid deadlock", "validation"),
            ("duplicate resource", "validation"),
            ("permission lock wait", "authorization"),
            ("not found limit exceeded", "data"),
        ]
        for msg, expected in cases:
            self.assertEqual(
                self.handler.categorize_error(Exception(msg)),
                expected,
                f"categorize_error({msg!r}) should be {expected!r}",
            )


class TestCalculateDelayParity(EnhancedTestCase):
    """Pin exact calculate_delay outputs under a fixed RNG (attempts 0..4).

    base=1, multiplier=2 (0-based) with +10% jitter at rng()=0.5 -> jitter is
    exactly +5%. The refactor routes through calculate_backoff_delay (1-based, so
    attempt+1) and MUST reproduce these exact values.
    """

    def setUp(self):
        super().setUp()
        self.handler = SEPAErrorHandler()

    def test_exact_values_fixed_rng(self):
        expected = {0: 1.05, 1: 2.1, 2: 4.2, 3: 8.4, 4: 16.8}
        # Patch stdlib random.random so this works against both the pre-refactor
        # implementation (which does `import random; random.random()`) and the
        # post-refactor one (which delegates to calculate_backoff_delay with the
        # default rng=random.random).
        with patch("random.random", return_value=0.5):
            for attempt, value in expected.items():
                self.assertAlmostEqual(self.handler.calculate_delay(attempt), value, places=9)

    def test_cap_then_jitter_fixed_rng(self):
        # attempt 20 -> nominal explodes, capped to 60 BEFORE jitter -> 60*1.05.
        with patch("random.random", return_value=0.5):
            self.assertAlmostEqual(self.handler.calculate_delay(20), 63.0, places=9)


class TestCircuitBreakerStateMachine(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.handler = SEPAErrorHandler()

    def test_closed_allows(self):
        self.assertTrue(self.handler.check_circuit_breaker())

    def test_opens_after_threshold_failures(self):
        for _ in range(5):
            self.handler.record_failure(Exception("timeout"))
        self.assertEqual(self.handler.circuit_breaker["state"], "open")
        self.assertFalse(self.handler.check_circuit_breaker())

    def test_does_not_open_below_threshold(self):
        for _ in range(4):
            self.handler.record_failure(Exception("timeout"))
        self.assertEqual(self.handler.circuit_breaker["state"], "closed")
        self.assertTrue(self.handler.check_circuit_breaker())

    def test_open_moves_to_half_open_after_recovery_timeout(self):
        for _ in range(5):
            self.handler.record_failure(Exception("timeout"))
        self.assertEqual(self.handler.circuit_breaker["state"], "open")
        # Simulate the recovery timeout having elapsed.
        self.handler.circuit_breaker["last_failure_time"] = now_datetime() - timedelta(seconds=400)
        allowed = self.handler.check_circuit_breaker()
        self.assertTrue(allowed)
        self.assertEqual(self.handler.circuit_breaker["state"], "half_open")
        self.assertEqual(self.handler.circuit_breaker["failure_count"], 0)

    def test_open_stays_open_before_recovery_timeout(self):
        for _ in range(5):
            self.handler.record_failure(Exception("timeout"))
        self.handler.circuit_breaker["last_failure_time"] = now_datetime() - timedelta(seconds=10)
        self.assertFalse(self.handler.check_circuit_breaker())
        self.assertEqual(self.handler.circuit_breaker["state"], "open")

    def test_half_open_allows_limited_calls(self):
        self.handler.circuit_breaker["state"] = "half_open"
        self.handler.circuit_breaker["failure_count"] = 0
        self.assertTrue(self.handler.check_circuit_breaker())
        self.handler.circuit_breaker["failure_count"] = 3  # == half_open_max_calls
        self.assertFalse(self.handler.check_circuit_breaker())

    def test_record_success_closes_half_open(self):
        self.handler.circuit_breaker["state"] = "half_open"
        self.handler.circuit_breaker["failure_count"] = 2
        self.handler.record_success()
        self.assertEqual(self.handler.circuit_breaker["state"], "closed")
        self.assertEqual(self.handler.circuit_breaker["failure_count"], 0)

    def test_record_success_noop_when_closed(self):
        self.handler.record_success()
        self.assertEqual(self.handler.circuit_breaker["state"], "closed")

    def test_reset_circuit_breaker(self):
        for _ in range(5):
            self.handler.record_failure(Exception("timeout"))
        self.handler.reset_circuit_breaker()
        self.assertEqual(self.handler.circuit_breaker["state"], "closed")
        self.assertEqual(self.handler.circuit_breaker["failure_count"], 0)
        self.assertIsNone(self.handler.circuit_breaker["last_failure_time"])

    def test_get_circuit_breaker_status(self):
        self.handler.record_failure(Exception("timeout"))
        status = self.handler.get_circuit_breaker_status()
        self.assertEqual(status["state"], "closed")
        self.assertEqual(status["failure_count"], 1)
        self.assertEqual(status["failure_threshold"], 5)
        self.assertEqual(status["recovery_timeout"], 300)


class TestExecuteWithRetry(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.handler = SEPAErrorHandler()

    def test_success_first_try(self):
        def op(x):
            return x * 2

        result = self.handler.execute_with_retry(op, 21)
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], 42)
        self.assertEqual(result["retries_attempted"], 0)
        self.assertEqual(result["operation"], "op")

    def test_blocked_by_open_circuit(self):
        for _ in range(5):
            self.handler.record_failure(Exception("timeout"))
        # Circuit is open and within recovery timeout.
        result = self.handler.execute_with_retry(lambda: 1)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_category"], "circuit_breaker")
        self.assertEqual(result["retries_attempted"], 0)

    def test_non_retryable_returns_immediately(self):
        calls = []

        def op():
            calls.append(1)
            raise Exception("invalid data")  # validation -> no retry

        with patch.object(seh.time, "sleep") as sleep_mock:
            result = self.handler.execute_with_retry(op)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_category"], "validation")
        self.assertTrue(result["final_attempt"])
        self.assertEqual(len(calls), 1)
        sleep_mock.assert_not_called()

    def test_retries_then_succeeds(self):
        attempts = []

        def op():
            attempts.append(1)
            if len(attempts) < 3:
                raise Exception("connection timeout")  # temporary
            return "ok"

        with patch.object(seh.time, "sleep"):
            result = self.handler.execute_with_retry(op)
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["retries_attempted"], 2)
        self.assertEqual(len(attempts), 3)

    def test_non_retryable_returns_final_attempt(self):
        # A non-retryable (validation) error returns immediately through the
        # `not should_retry` branch with final_attempt=True, NOT the post-loop
        # retries_exhausted branch (the error was never eligible for retry).
        def op():
            raise Exception("invalid data")  # validation, never retried

        with patch.object(seh.time, "sleep"):
            result = self.handler.execute_with_retry(op)
        self.assertFalse(result["success"])
        self.assertTrue(result.get("final_attempt"))
        self.assertIsNone(result.get("retries_exhausted"))
        self.assertEqual(result["retries_attempted"], 0)
        # One failure recorded on the circuit breaker.
        self.assertEqual(self.handler.circuit_breaker["failure_count"], 1)

    def test_retries_exhausted_flag_is_reachable(self):
        """A fully-exhausted retry sequence surfaces retries_exhausted=True.

        A persistently-temporary error is retried max_retries (3) times. After
        the final retry attempt fails, the retry sequence is exhausted and the
        function falls through to the post-loop block, returning
        retries_exhausted=True (the terminal result for a retryable error that
        keeps failing). This is distinct from final_attempt=True, which is the
        terminal result for a non-retryable error.
        """
        def op():
            raise Exception("server timeout")  # temporary, always fails

        with patch.object(seh.time, "sleep"):
            result = self.handler.execute_with_retry(op)
        self.assertFalse(result["success"])
        self.assertTrue(result.get("retries_exhausted"))
        # An exhausted retryable error is NOT a single final_attempt.
        self.assertIsNone(result.get("final_attempt"))
        self.assertEqual(result["retries_attempted"], 3)
        self.assertEqual(result["error_category"], "temporary")
        # One failure recorded on the circuit breaker for the whole sequence.
        self.assertEqual(self.handler.circuit_breaker["failure_count"], 1)

    def test_success_after_failure_closes_half_open(self):
        self.handler.circuit_breaker["state"] = "half_open"
        self.handler.circuit_breaker["failure_count"] = 1
        result = self.handler.execute_with_retry(lambda: "done")
        self.assertTrue(result["success"])
        self.assertEqual(self.handler.circuit_breaker["state"], "closed")


class TestCreateRetryBatch(EnhancedTestCase):
    def test_no_retryable_operations(self):
        handler = SEPAErrorHandler()
        failed = [
            {"operation": "x", "error_category": "validation"},
            {"operation": "y", "error_category": "data"},
            {"operation": "z", "error_category": "temporary", "retries_exhausted": True},
        ]
        result = handler.create_retry_batch(failed)
        self.assertFalse(result["success"])
        self.assertEqual(result["retryable_count"], 0)
        self.assertEqual(result["total_failed"], 3)

    def test_creates_batch_for_retryable(self):
        handler = SEPAErrorHandler()
        failed = [
            {
                "operation": "validate_mandate",
                "error": "connection timeout",
                "error_category": "temporary",
                "retries_attempted": 2,
                "reference_document": "SEPA-001",
            },
            {"operation": "weird", "error": "huh", "error_category": "unknown"},
            {"operation": "bad", "error": "invalid", "error_category": "validation"},
        ]
        result = handler.create_retry_batch(failed)
        try:
            self.assertTrue(result["success"], msg=str(result))
            self.assertEqual(result["retryable_count"], 2)
            self.assertEqual(result["total_failed"], 3)
            # Verify the persisted document. (total_operations is recomputed by
            # the doctype's own validate() via SQL aggregation over committed
            # child rows, so we assert on the in-memory child rows instead.)
            batch = frappe.get_doc("SEPA Retry Batch", result["retry_batch"])
            self.assertTrue(batch.created_by_error_handler)
            self.assertEqual(len(batch.operations), 2)
            # operation_type is a Select: the caller's raw operation name is
            # normalised onto an option, and anything unrecognised becomes "Other".
            op_types = {op.operation_type for op in batch.operations}
            self.assertEqual(op_types, {"Mandate Validation", "Other"})
        finally:
            if result.get("retry_batch"):
                frappe.delete_doc("SEPA Retry Batch", result["retry_batch"], force=True)


class TestSepaRetryDecorator(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # Reset the module singleton so the decorator uses a fresh handler.
        seh._error_handler = None

    def tearDown(self):
        seh._error_handler = None
        super().tearDown()

    def test_decorator_returns_result_on_success(self):
        @sepa_retry("my_op")
        def add(a, b):
            return a + b

        self.assertEqual(add(2, 3), 5)

    def test_decorator_raises_on_non_circuit_failure(self):
        @sepa_retry("failing_op")
        def boom():
            raise Exception("invalid input")  # validation -> no retry, re-raised

        with self.assertRaises(Exception) as ctx:
            boom()
        self.assertIn("invalid input", str(ctx.exception))

    def test_decorator_defaults_operation_name_to_func_name(self):
        @sepa_retry()
        def named_op():
            raise Exception("not found")  # data -> no retry, re-raised

        with self.assertRaises(Exception):
            named_op()

    def test_decorator_does_not_crash_when_circuit_open(self):
        """When the circuit is open, @sepa_retry raises a clear exception.

        When the circuit breaker is open, execute_with_retry returns early with
        a dict that has NO "result" key. The decorator must not blindly index
        result["result"] (which would KeyError); instead it surfaces the
        circuit-open error as a regular Exception, consistent with how it
        re-raises every other failure category.
        """
        handler = get_sepa_error_handler()
        for _ in range(5):
            handler.record_failure(Exception("timeout"))
        self.assertEqual(handler.circuit_breaker["state"], "open")

        @sepa_retry("blocked_op")
        def op():
            return "never runs"

        with self.assertRaises(Exception) as ctx:
            op()
        # The exception surfaces the circuit-open error, not a KeyError.
        self.assertNotIsInstance(ctx.exception, KeyError)
        self.assertIn("Circuit breaker", str(ctx.exception))


class TestSingletonAndAPIs(EnhancedTestCase):
    def test_get_sepa_error_handler_is_singleton(self):
        seh._error_handler = None
        a = get_sepa_error_handler()
        b = get_sepa_error_handler()
        self.assertIs(a, b)

    def test_status_api(self):
        seh._error_handler = None
        status = seh.get_sepa_error_handler_status()
        self.assertIn("state", status)
        self.assertIn("failure_count", status)

    def test_reset_api(self):
        handler = get_sepa_error_handler()
        for _ in range(5):
            handler.record_failure(Exception("timeout"))
        result = seh.reset_sepa_circuit_breaker()
        self.assertTrue(result["success"])
        self.assertEqual(handler.circuit_breaker["state"], "closed")

    def test_create_retry_batch_api_parses_json_string(self):
        import json

        seh._error_handler = None
        error_data = json.dumps(
            [{"operation": "x", "error_category": "validation"}]
        )
        result = seh.create_retry_batch_from_errors(error_data)
        # Validation-only -> nothing retryable, no doc created.
        self.assertFalse(result["success"])
        self.assertEqual(result["retryable_count"], 0)

    def test_create_retry_batch_api_accepts_list(self):
        seh._error_handler = None
        result = seh.create_retry_batch_from_errors(
            [{"operation": "x", "error_category": "data"}]
        )
        self.assertFalse(result["success"])


class TestCreateRetryBatchPersists(VereningingenTestCase):
    """
    The "operation" key is a Python function name (execute_with_retry passes
    ``operation.__name__``) or free text from an API caller, and it was written
    straight into the operation_type Select — where even the hardcoded "unknown"
    fallback is not an option. No retry batch could ever be saved.

    On VereningingenTestCase, not EnhancedTestCase: the latter sets in_import,
    which skips _validate_selects() and hides the whole defect.
    """

    def setUp(self):
        super().setUp()
        seh._error_handler = None
        self.handler = get_sepa_error_handler()

    def _retryable(self, operation):
        return [{"operation": operation, "error": "gateway timeout", "error_category": "temporary"}]

    def test_function_name_maps_onto_the_matching_option(self):
        result = self.handler.create_retry_batch(self._retryable("validate_mandate"))
        self.assertTrue(result["success"], result)
        self.track_doc("SEPA Retry Batch", result["retry_batch"])
        batch = frappe.get_doc("SEPA Retry Batch", result["retry_batch"])
        self.assertEqual(batch.operations[0].operation_type, "Mandate Validation")

    def test_unrecognised_operation_becomes_other_and_keeps_the_original_name(self):
        result = self.handler.create_retry_batch(self._retryable("reticulate_splines"))
        self.assertTrue(result["success"], result)
        self.track_doc("SEPA Retry Batch", result["retry_batch"])
        batch = frappe.get_doc("SEPA Retry Batch", result["retry_batch"])
        self.assertEqual(batch.operations[0].operation_type, "Other")
        # The caller's own name is the only way to tell two "Other" rows apart.
        self.assertEqual(batch.operations[0].retry_notes, "reticulate_splines")

    def test_caller_supplied_option_is_passed_through_unchanged(self):
        result = self.handler.create_retry_batch(self._retryable("Batch Processing"))
        self.assertTrue(result["success"], result)
        self.track_doc("SEPA Retry Batch", result["retry_batch"])
        batch = frappe.get_doc("SEPA Retry Batch", result["retry_batch"])
        self.assertEqual(batch.operations[0].operation_type, "Batch Processing")
        self.assertFalse(batch.operations[0].retry_notes)


if __name__ == "__main__":
    unittest.main()
