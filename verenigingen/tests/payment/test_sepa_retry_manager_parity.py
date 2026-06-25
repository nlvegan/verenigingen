# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Characterization / parity tests for
``verenigingen_payments.utils.sepa_retry_manager``.

These tests pin the CURRENT (pre-refactor) behavior of the two pieces that the
DRY refactor touches:

  * ``SEPARetryManager._classify_failure`` — its failure-type taxonomy uses a
    DIFFERENT keyword bucketing than the shared classifier (e.g. "busy" /
    "unavailable" are RESOURCE here but TRANSIENT in the shared classifier;
    "missing"/"duplicate"/"constraint" are NOT validation here; there is no
    AUTHORIZATION/DATA bucket). It also has the isinstance(SEPAError)->BUSINESS
    and frappe.PermissionError->PERMANENT special cases. Because of these
    divergences this method keeps its own keyword logic; the parity table guards
    against any accidental behavior change during the refactor.

  * ``SEPARetryManager._calculate_delay`` — exponential/linear/fixed/fibonacci
    backoff with a per-failure-type modifier (TRANSIENT*0.5, RESOURCE*1.5)
    applied BEFORE the max_delay cap, then jitter. The refactor delegates the
    raw strategy math to ``calculate_backoff_delay`` (uncapped, no jitter) and
    re-applies the modifier/cap/jitter in the caller; the exact outputs under a
    fixed RNG must be preserved.

Error inputs are REAL exceptions; no business logic is mocked. The only patched
boundary is stdlib ``random.random`` (so jitter is deterministic).
"""

import unittest
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.error_handling import SEPAError
from verenigingen.verenigingen_payments.utils.sepa_retry_manager import (
    FailureType,
    RetryConfig,
    RetryStrategy,
    SEPARetryManager,
)


class TestClassifyFailureParity(EnhancedTestCase):
    """Pin the exact FailureType returned for a representative input set."""

    # (message, expected FailureType)
    PARITY_TABLE = [
        ("connection refused", FailureType.TRANSIENT),
        ("request timeout", FailureType.TRANSIENT),
        ("deadlock detected", FailureType.TRANSIENT),
        ("lock wait timeout exceeded", FailureType.TRANSIENT),
        ("temporary glitch", FailureType.TRANSIENT),
        ("connection invalid", FailureType.TRANSIENT),  # transient checked first
        # RESOURCE bucket (diverges from shared classifier, which calls these
        # TRANSIENT): "busy"/"unavailable"/"resource"/"limit exceeded".
        ("server busy", FailureType.RESOURCE),
        ("network unavailable", FailureType.RESOURCE),
        ("resource busy", FailureType.RESOURCE),
        ("resource unavailable", FailureType.RESOURCE),
        ("limit exceeded", FailureType.RESOURCE),
        # These have NO keyword in this method's narrow buckets -> SYSTEM.
        ("overload", FailureType.SYSTEM),
        ("missing field", FailureType.SYSTEM),
        ("duplicate entry", FailureType.SYSTEM),
        ("constraint violation", FailureType.SYSTEM),
        ("unauthorized access", FailureType.SYSTEM),
        ("forbidden", FailureType.SYSTEM),
        ("authentication failed", FailureType.SYSTEM),
        ("record not found", FailureType.SYSTEM),
        ("does not exist", FailureType.SYSTEM),
        ("result is empty", FailureType.SYSTEM),
        ("value is null", FailureType.SYSTEM),
        ("something weird happened", FailureType.SYSTEM),
        # VALIDATION keywords.
        ("invalid mandate", FailureType.VALIDATION),
        ("format error", FailureType.VALIDATION),
        ("validation failed", FailureType.VALIDATION),
        ("required field", FailureType.VALIDATION),
        # PERMANENT via "permission" keyword.
        ("permission denied", FailureType.PERMANENT),
    ]

    def setUp(self):
        super().setUp()
        self.manager = SEPARetryManager()

    def test_keyword_parity_table(self):
        for msg, expected in self.PARITY_TABLE:
            self.assertEqual(self.manager._classify_failure(Exception(msg)), expected, msg)

    def test_isinstance_validation(self):
        self.assertEqual(self.manager._classify_failure(ValueError("x")), FailureType.VALIDATION)
        self.assertEqual(self.manager._classify_failure(TypeError("x")), FailureType.VALIDATION)

    def test_isinstance_permission_is_permanent(self):
        self.assertEqual(
            self.manager._classify_failure(frappe.PermissionError("x")), FailureType.PERMANENT
        )

    def test_sepa_error_is_business(self):
        # isinstance(SEPAError) wins over the (absent) keyword for plain "x"...
        self.assertEqual(self.manager._classify_failure(SEPAError("x")), FailureType.BUSINESS)

    def test_keyword_precedes_sepa_error_business(self):
        # ...but a SEPAError whose MESSAGE matches an earlier keyword bucket is
        # classified by that keyword (keyword checks run before isinstance SEPAError).
        self.assertEqual(self.manager._classify_failure(SEPAError("timeout")), FailureType.TRANSIENT)
        self.assertEqual(self.manager._classify_failure(SEPAError("resource")), FailureType.RESOURCE)
        self.assertEqual(self.manager._classify_failure(SEPAError("invalid")), FailureType.VALIDATION)

    def test_sepa_error_business_precedes_permission_keyword(self):
        # SEPAError isinstance check runs BEFORE the "permission" keyword check,
        # so a SEPAError("permission ...") is BUSINESS, not PERMANENT.
        self.assertEqual(self.manager._classify_failure(SEPAError("permission")), FailureType.BUSINESS)


class TestCalculateDelayParity(EnhancedTestCase):
    """Pin exact _calculate_delay outputs for all strategies / modifiers."""

    def setUp(self):
        super().setUp()
        self.manager = SEPARetryManager()

    def _table(self, strategy, max_delay=60.0):
        return RetryConfig(strategy=strategy, max_delay=max_delay)

    def test_exponential_with_modifiers_fixed_rng(self):
        # base=1, exp_base=2, jitter=0.1; rng()=0.5 -> +5%.
        cfg = self._table(RetryStrategy.EXPONENTIAL)
        # attempt -> (transient, resource, system)
        expected = {
            1: (0.525, 1.575, 1.05),
            2: (1.05, 3.15, 2.1),
            3: (2.1, 6.3, 4.2),
            4: (4.2, 12.6, 8.4),
            5: (8.4, 25.2, 16.8),
        }
        with patch("random.random", return_value=0.5):
            for attempt, (t, r, s) in expected.items():
                self.assertAlmostEqual(
                    self.manager._calculate_delay(attempt, cfg, FailureType.TRANSIENT), t, places=9
                )
                self.assertAlmostEqual(
                    self.manager._calculate_delay(attempt, cfg, FailureType.RESOURCE), r, places=9
                )
                self.assertAlmostEqual(
                    self.manager._calculate_delay(attempt, cfg, FailureType.SYSTEM), s, places=9
                )

    def test_linear_fixed_fibonacci_system_fixed_rng(self):
        with patch("random.random", return_value=0.5):
            linear = self._table(RetryStrategy.LINEAR)
            self.assertAlmostEqual(
                self.manager._calculate_delay(3, linear, FailureType.SYSTEM), 3.15, places=9
            )
            fixed = self._table(RetryStrategy.FIXED)
            self.assertAlmostEqual(
                self.manager._calculate_delay(4, fixed, FailureType.SYSTEM), 1.05, places=9
            )
            fib = self._table(RetryStrategy.FIBONACCI)
            self.assertAlmostEqual(
                self.manager._calculate_delay(5, fib, FailureType.SYSTEM), 5.25, places=9
            )

    def test_modifier_applied_before_cap_fixed_rng(self):
        # With a tight cap, RESOURCE*1.5 must be applied BEFORE the cap.
        # exponential a4 = 8; *1.5 = 12; capped to 5; +5% jitter -> 5.25.
        cfg = self._table(RetryStrategy.EXPONENTIAL, max_delay=5.0)
        with patch("random.random", return_value=0.5):
            self.assertAlmostEqual(
                self.manager._calculate_delay(4, cfg, FailureType.RESOURCE), 5.25, places=9
            )

    def test_no_jitter_when_factor_zero(self):
        cfg = RetryConfig(strategy=RetryStrategy.EXPONENTIAL, jitter_factor=0.0)
        # No jitter -> exact nominal * modifier.
        self.assertAlmostEqual(
            self.manager._calculate_delay(3, cfg, FailureType.SYSTEM), 4.0, places=9
        )
        self.assertAlmostEqual(
            self.manager._calculate_delay(3, cfg, FailureType.TRANSIENT), 2.0, places=9
        )


if __name__ == "__main__":
    unittest.main()
