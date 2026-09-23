"""
Unit coverage for MolliePerformanceMonitor.metrics being bounded (#1304).

`MolliePerformanceMonitor.metrics` (utils/monitoring.py) is a plain list on a
process-local singleton (`performance_monitor`, instantiated once at import
time). `record_operation()` appends to it unconditionally, and it is on the
live Mollie webhook path -- `record_operation_performance()` is called from 8
sites in `webhook_wrapper_service_unified.py` on every webhook processed,
success and failure alike. Nothing ever trimmed it, so it grew without bound
for the life of the worker (same singleton-lifetime shape as #1177/#962).

Fixed the same way `ServiceMetrics` and `FinancialErrorHandler` (#1177) already
bound their own history: `collections.deque(maxlen=MAX_METRICS_SIZE)`.

These tests instantiate a *fresh* MolliePerformanceMonitor rather than reusing
the module-level singleton, so they cannot be poisoned by (or poison) other
tests sharing that singleton across the suite -- see the snapshot/restore
dance in test_mollie_monitoring_api_unit.py, which this file does not need.
"""

import json

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.utils.monitoring import (
    MolliePerformanceMonitor,
)

# The bound this fix introduces. Deliberately a literal, not
# MolliePerformanceMonitor.MAX_METRICS_SIZE: reading the class constant would
# make every size/eviction assertion below fail with AttributeError against
# the pre-fix code (which has no such attribute) instead of failing because
# the list actually kept growing -- the wrong reason, and indistinguishable
# from a typo in the test itself. A literal fails for the right reason on
# both sides of the fix.
EXPECTED_MAX_METRICS_SIZE = 1000


class TestMetricsIsBounded(EnhancedTestCase):
    """self.metrics must not grow past MAX_METRICS_SIZE (#1304)."""

    def setUp(self):
        super().setUp()
        self.monitor = MolliePerformanceMonitor()

    def test_the_bound_constant_matches_what_these_tests_assume(self):
        self.assertEqual(MolliePerformanceMonitor.MAX_METRICS_SIZE, EXPECTED_MAX_METRICS_SIZE)

    def test_metrics_does_not_grow_past_the_bound(self):
        max_size = EXPECTED_MAX_METRICS_SIZE
        overflow = 5

        for i in range(max_size + overflow):
            # Alternate operations so multiple operation "buckets" stay
            # populated in the retained window, exercising get_operation_stats
            # below with more than one operation type present.
            operation = "webhook_processing" if i % 2 == 0 else "payment_creation"
            self.monitor.record_operation(operation, duration=0.01, success=True, details={"i": i})

        self.assertEqual(len(self.monitor.metrics), max_size)

    def test_most_recent_entries_are_kept_oldest_dropped(self):
        max_size = EXPECTED_MAX_METRICS_SIZE
        overflow = 5
        total = max_size + overflow

        for i in range(total):
            self.monitor.record_operation(
                "webhook_processing", duration=0.01, success=True, details={"i": i}
            )

        indices = [m.details["i"] for m in self.monitor.metrics]
        # The oldest `overflow` entries (0..overflow-1) were evicted; the
        # newest entry (total - 1) is retained.
        self.assertNotIn(0, indices)
        self.assertNotIn(overflow - 1, indices)
        self.assertIn(overflow, indices)
        self.assertIn(total - 1, indices)

    def test_get_operation_stats_reports_over_the_retained_window(self):
        max_size = EXPECTED_MAX_METRICS_SIZE
        overflow = 3

        # Fill past the bound with a "stale_operation" that will be entirely
        # evicted...
        for _ in range(overflow):
            self.monitor.record_operation("stale_operation", duration=0.01, success=True)
        # ...then fill the rest of the window with the operation under test,
        # which survives.
        for _ in range(max_size):
            self.monitor.record_operation("webhook_processing", duration=0.5, success=True)

        stats = self.monitor.get_operation_stats("webhook_processing", hours=24)
        self.assertEqual(stats["total_calls"], max_size)
        self.assertEqual(stats["success_rate"], 100)

        # The evicted stale_operation entries no longer count at all.
        stale_stats = self.monitor.get_operation_stats("stale_operation", hours=24)
        self.assertEqual(stale_stats["total_calls"], 0)

    def test_positive_control_a_few_operations_report_correctly(self):
        """A legitimate, un-evicted case still works: stats over a handful of
        recorded operations are correct, not just the eviction boundary."""
        self.monitor.record_operation("payment_creation", duration=1.0, success=True)
        self.monitor.record_operation("payment_creation", duration=3.0, success=False)

        stats = self.monitor.get_operation_stats("payment_creation", hours=24)
        self.assertEqual(stats["total_calls"], 2)
        self.assertEqual(stats["success_rate"], 50)
        self.assertEqual(stats["avg_duration"], 2.0)
        self.assertEqual(stats["max_duration"], 3.0)
        self.assertEqual(stats["min_duration"], 1.0)
        self.assertEqual(stats["slow_operations"], 1)

    def test_get_overall_health_reports_over_the_retained_window(self):
        max_size = EXPECTED_MAX_METRICS_SIZE
        overflow = 4

        for _ in range(overflow):
            self.monitor.record_operation("evicted_op", duration=0.01, success=False)
        for _ in range(max_size):
            self.monitor.record_operation("webhook_processing", duration=0.01, success=True)

        health = self.monitor.get_overall_health(hours=24)
        self.assertEqual(health["total_operations"], max_size)
        self.assertEqual(health["overall_success_rate"], 100)
        self.assertNotIn("evicted_op", health["operations_by_type"])
        self.assertIn("webhook_processing", health["operations_by_type"])


class TestMetricsSurvivesRealReaderPaths(EnhancedTestCase):
    """Exercise the readers through their real, whitelisted paths and confirm
    the bounded deque still serialises fine (#1304's caution: a deque breaks
    slicing/sort/json.dumps of the raw object if any reader relies on
    list-only behaviour)."""

    def setUp(self):
        super().setUp()
        from unittest.mock import patch

        from verenigingen.utils.security.types import EnvironmentLevel
        from verenigingen.verenigingen_payments.mollie.utils.monitoring import (
            performance_monitor,
        )

        self._env_patch = patch(
            "verenigingen.utils.security.environment_validator.EnvironmentValidator.get_current_environment",
            return_value=EnvironmentLevel.DEVELOPMENT,
        )
        self._env_patch.start()

        # performance_monitor.metrics is the process-global singleton shared
        # across the whole suite (see test_mollie_monitoring_api_unit.py's
        # own snapshot/restore for the same reason). Snapshot and clear it so
        # this test starts from a known-empty deque.
        self._perf_monitor = performance_monitor
        self._saved_metrics = list(performance_monitor.metrics)
        performance_monitor.metrics.clear()

    def tearDown(self):
        self._perf_monitor.metrics.clear()
        self._perf_monitor.metrics.extend(self._saved_metrics)
        self._env_patch.stop()
        super().tearDown()

    def test_whitelisted_get_performance_metrics_endpoint_serialises(self):
        from verenigingen.verenigingen_payments.mollie.api import monitoring_api

        for i in range(10):
            monitoring_api.performance_monitor.record_operation(
                "webhook_processing", duration=0.2, success=True, details={"i": i}
            )

        with self.set_user("Administrator"):
            result = monitoring_api.get_performance_metrics()

        # The endpoint must produce a plain dict built from the bounded
        # deque, and that dict must still be JSON-serialisable through
        # frappe's own serialiser (the whitelisted-endpoint response path).
        serialised = frappe.as_json(result)
        parsed = json.loads(serialised)
        self.assertEqual(parsed["operations"]["webhook_processing"]["total_calls"], 10)

    def test_whitelisted_clear_performance_data_endpoint_clears_bounded_deque(self):
        from verenigingen.verenigingen_payments.mollie.api import monitoring_api

        monitoring_api.performance_monitor.record_operation(
            "webhook_processing", duration=0.1, success=True
        )
        self.assertEqual(len(monitoring_api.performance_monitor.metrics), 1)

        with self.set_user("Administrator"):
            result = monitoring_api.clear_performance_data()

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(monitoring_api.performance_monitor.metrics), 0)

    def test_whitelisted_get_integration_health_endpoint_serialises(self):
        from verenigingen.verenigingen_payments.mollie.api import monitoring_api

        monitoring_api.performance_monitor.record_operation(
            "webhook_processing", duration=0.1, success=True
        )

        with self.set_user("Administrator"):
            result = monitoring_api.get_integration_health()

        serialised = frappe.as_json(result)
        parsed = json.loads(serialised)
        self.assertIn("performance_metrics", parsed)
