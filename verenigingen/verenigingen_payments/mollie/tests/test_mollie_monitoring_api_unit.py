"""
Integration coverage (Tier-2) for the Mollie monitoring API — api/monitoring_api.py.

These whitelisted endpoints aggregate the monitoring + error-recovery subsystems
(health checks, performance metrics, circuit-breaker administration, recovery-queue
processing). They issue no outbound Mollie calls in the paths exercised here, so
they run with no credentials. Endpoints are invoked through their real
@frappe.whitelist + security-tier wrappers as Administrator (the test env has
developer_mode enabled, satisfying the development_only_api gate), so the decorator
plumbing is exercised exactly as in production.

We drive deterministic outcomes by seeding the module-global error_recovery
singleton's in-memory state (circuit breakers / recovery queues) before calling
the admin endpoints, then assert the endpoint reports/mutates exactly that state.

Targets (verenigingen/verenigingen_payments/mollie/api/monitoring_api.py):
  - get_integration_health / get_performance_metrics / get_service_status
  - get_error_recovery_status
  - reset_circuit_breakers (admin)
  - process_recovery_queues (admin: all-queues + named-queue + unknown-queue throw)
  - run_health_check / clear_performance_data / test_error_recovery (dev-only)
  - _get_recovery_performance_metrics
  - _calculate_recovery_system_health (excellent/good/fair/poor + exception path)
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api import monitoring_api
from verenigingen.verenigingen_payments.mollie.utils.error_recovery import (
    CircuitBreakerState,
    error_recovery,
)


class TestRecoverySystemHealthCalc(EnhancedTestCase):
    """_calculate_recovery_system_health — pure scoring logic."""

    def test_excellent_when_clean(self):
        result = monitoring_api._calculate_recovery_system_health(
            {"circuit_breakers": {}, "recovery_queues": {}}, {}
        )
        self.assertEqual(result, "excellent")

    def test_open_circuit_degrades_to_good(self):
        # One open circuit deducts 20 -> score 80 -> "good"
        status = {
            "circuit_breakers": {"c1": {"is_open": True}},
            "recovery_queues": {},
        }
        self.assertEqual(monitoring_api._calculate_recovery_system_health(status, {}), "good")

    def test_two_open_circuits_fair(self):
        # Two open circuits -> 60 -> "fair"
        status = {
            "circuit_breakers": {"c1": {"is_open": True}, "c2": {"is_open": True}},
            "recovery_queues": {},
        }
        self.assertEqual(monitoring_api._calculate_recovery_system_health(status, {}), "fair")

    def test_pending_backlog_and_open_circuits_poor(self):
        # 3 open circuits (-60) + big backlog (-30) -> 10 -> "poor"
        status = {
            "circuit_breakers": {"c1": {"is_open": True}, "c2": {"is_open": True}, "c3": {"is_open": True}},
            "recovery_queues": {"q": {"pending": 50}},
        }
        self.assertEqual(monitoring_api._calculate_recovery_system_health(status, {}), "poor")

    def test_malformed_input_returns_unknown(self):
        # circuit_breakers as a non-dict triggers the except branch
        self.assertEqual(
            monitoring_api._calculate_recovery_system_health({"circuit_breakers": None}, {}), "unknown"
        )


class TestRecoveryPerformanceMetrics(EnhancedTestCase):
    """_get_recovery_performance_metrics — cache-backed aggregation."""

    def test_returns_metrics_for_known_operations(self):
        metrics = monitoring_api._get_recovery_performance_metrics()
        # Always returns the three tracked operations with the expected shape
        for op in ("webhook_processing", "payment_creation", "refund_creation"):
            self.assertIn(op, metrics)
            self.assertIn("recovery_success", metrics[op])
            self.assertIn("operation_failures", metrics[op])
            self.assertIn("recovery_rate", metrics[op])
            # recovery_rate is a computed number, not just a present key
            self.assertIsInstance(metrics[op]["recovery_rate"], (int, float))

    def test_recovery_rate_computed_from_cache_counters(self):
        """Seed the cache counters the metric reads and assert the rate math:
        recovery_rate = recovery_success.count / max(failures.count, 1) * 100.

        Regression: error_recovery.py stores these counters as JSON strings and
        frappe.cache().get returns bytes, but _get_recovery_performance_metrics
        indexed them as dicts -> raised -> the whole helper returned {} the moment
        any recovery activity existed. The shared _read_recovery_counter now
        deserialises them."""
        import json

        op = "webhook_processing"
        frappe.cache().set(
            f"mollie_recovery_success:{op}", json.dumps({"count": 3, "total_attempts": 9}), 3600
        )
        frappe.cache().set(
            f"mollie_operation_failure:{op}", json.dumps({"count": 6, "total_attempts": 6}), 3600
        )
        try:
            metrics = monitoring_api._get_recovery_performance_metrics()
            # 3 / 6 * 100 == 50.0
            self.assertEqual(metrics[op]["recovery_rate"], 50.0)
            self.assertEqual(metrics[op]["recovery_success"]["count"], 3)
            self.assertEqual(metrics[op]["operation_failures"]["count"], 6)
        finally:
            frappe.cache().delete_value(f"mollie_recovery_success:{op}")
            frappe.cache().delete_value(f"mollie_operation_failure:{op}")


class TestErrorRecoveryStatusEndpoint(EnhancedTestCase):
    """get_error_recovery_status — read-only aggregation endpoint."""

    def test_reports_seeded_circuit_breaker(self):
        with self.set_user("Administrator"):
            cb_name = f"unit_status_{frappe.generate_hash()[:8]}"
            error_recovery.circuit_breakers[cb_name] = CircuitBreakerState(is_open=True, failure_count=7)
            try:
                result = monitoring_api.get_error_recovery_status()
                self.assertIn("circuit_breakers", result)
                self.assertIn(cb_name, result["circuit_breakers"])
                self.assertTrue(result["circuit_breakers"][cb_name]["is_open"])
                self.assertEqual(result["circuit_breakers"][cb_name]["failure_count"], 7)
                self.assertIn("system_health", result)
                self.assertIn("performance_metrics", result)
            finally:
                error_recovery.circuit_breakers.pop(cb_name, None)


class TestResetCircuitBreakers(EnhancedTestCase):
    """reset_circuit_breakers — admin mutation endpoint."""

    def test_resets_open_circuit(self):
        with self.set_user("Administrator"):
            cb_name = f"unit_reset_{frappe.generate_hash()[:8]}"
            error_recovery.circuit_breakers[cb_name] = CircuitBreakerState(
                is_open=True, failure_count=9, success_count=2
            )
            try:
                result = monitoring_api.reset_circuit_breakers()
                self.assertEqual(result["status"], "success")
                self.assertIn(cb_name, result["reset_circuits"])
                # The actual in-memory state was reset
                state = error_recovery.circuit_breakers[cb_name]
                self.assertFalse(state.is_open)
                self.assertEqual(state.failure_count, 0)
                self.assertEqual(state.success_count, 0)
                self.assertIsNone(state.last_failure_time)
            finally:
                error_recovery.circuit_breakers.pop(cb_name, None)


class TestProcessRecoveryQueues(EnhancedTestCase):
    """process_recovery_queues — admin processing endpoint."""

    def _seed_queue(self, name, strategy="manual_review"):
        error_recovery.create_recovery_workflow(name, {"operation_type": "unit"}, strategy)

    def test_process_named_queue(self):
        with self.set_user("Administrator"):
            qname = f"unit_q_{frappe.generate_hash()[:8]}"
            self._seed_queue(qname)
            try:
                frappe.form_dict.queue_name = qname
                frappe.form_dict.max_items = 10
                result = monitoring_api.process_recovery_queues()
                self.assertEqual(result["status"], "success")
                self.assertIn(qname, result["results"])
                # manual_review strategy -> the single item completes
                self.assertEqual(result["results"][qname]["succeeded"], 1)
                self.assertEqual(result["summary"]["total_succeeded"], 1)
            finally:
                frappe.form_dict.pop("queue_name", None)
                frappe.form_dict.pop("max_items", None)
                error_recovery.recovery_queues.pop(qname, None)

    def test_unknown_queue_throws(self):
        with self.set_user("Administrator"):
            missing = f"no_such_{frappe.generate_hash()[:8]}"
            frappe.form_dict.queue_name = missing
            try:
                with self.assertRaises(frappe.ValidationError):
                    monitoring_api.process_recovery_queues()
            finally:
                frappe.form_dict.pop("queue_name", None)


class TestHealthAndPerformanceEndpoints(EnhancedTestCase):
    """The read endpoints + dev-only utilities all return well-formed payloads."""

    def test_get_integration_health_shape(self):
        with self.set_user("Administrator"):
            result = monitoring_api.get_integration_health()
            self.assertIn("health_check", result)
            self.assertIn("performance_metrics", result)
            self.assertIn("generated_at", result)

    def test_get_performance_metrics_respects_hours_param(self):
        with self.set_user("Administrator"):
            frappe.form_dict.hours = 12
            try:
                result = monitoring_api.get_performance_metrics()
                self.assertEqual(result["period_hours"], 12)
                self.assertIn("summary", result)
                self.assertIn("operations", result)
            finally:
                frappe.form_dict.pop("hours", None)

    def test_get_service_status_overall_status(self):
        with self.set_user("Administrator"):
            result = monitoring_api.get_service_status()
            self.assertIn("overall_status", result)
            self.assertIn(result["overall_status"], {"healthy", "degraded", "unhealthy"})
            self.assertIn("summary", result)
            self.assertEqual(
                result["summary"]["total_services"],
                result["summary"]["healthy"] + result["summary"]["unhealthy"],
            )

    def test_run_health_check_returns_overall_status(self):
        with self.set_user("Administrator"):
            result = monitoring_api.run_health_check()
            self.assertIn("overall_status", result)
            self.assertIn("summary", result)

    def test_clear_performance_data_empties_metrics(self):
        with self.set_user("Administrator"):
            from verenigingen.verenigingen_payments.mollie.utils.monitoring import performance_monitor

            performance_monitor.metrics.append("sentinel")
            result = monitoring_api.clear_performance_data()
            self.assertEqual(result["status"], "success")
            self.assertEqual(len(performance_monitor.metrics), 0, "metrics list should be cleared")

    def test_error_recovery_self_test_all_passed(self):
        """Regression: the retry sub-test referenced error_recovery.RetryConfig,
        but RetryConfig is a module-level class (not an instance attribute), so it
        raised AttributeError and the retry_mechanism self-test always reported
        'failed' / all_passed=False. After importing RetryConfig at module scope
        all three sub-tests pass."""
        with self.set_user("Administrator"):
            result = monitoring_api.test_error_recovery()
            # The endpoint exercises retry, circuit-breaker and workflow creation
            self.assertTrue(result["all_passed"], result.get("tests_run"))
            test_names = {t["test"] for t in result["tests_run"]}
            self.assertEqual(test_names, {"retry_mechanism", "circuit_breaker", "recovery_workflow"})
            self.assertTrue(all(t["status"] == "passed" for t in result["tests_run"]))
