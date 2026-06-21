"""
Coverage sweep for the service-infrastructure base classes.

Targets:
    - verenigingen/services/infrastructure/base_service.py
    - verenigingen/services/infrastructure/service_metrics.py

All tests use real DB writes (no business-logic mocking). Transaction tests
exercise StatefulService.execute_with_transaction against throwaway,
factory-tracked Member rows so the savepoint/rollback semantics are observable
in the database and cleaned up in tearDown.
"""

import time

import frappe

from verenigingen.services.infrastructure.base_service import (
    APIService,
    BaseService,
    DataService,
    StatefulService,
    StatelessService,
)
from verenigingen.services.infrastructure.service_metrics import (
    HealthMonitor,
    MetricsCollector,
    PerformanceProfiler,
    ServiceMetrics,
    get_health_monitor,
    get_metrics_collector,
    get_profiler,
    get_service_health,
    get_system_health,
    record_operation,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.service_error_handler import ServiceError


class _ConcreteBaseService(BaseService):
    """Minimal concrete subclass so BaseService (ABC) can be instantiated."""

    def validate_configuration(self) -> bool:
        return True


class BaseServiceTests(EnhancedTestCase):
    """Direct coverage of BaseService bookkeeping helpers."""

    def test_metrics_lifecycle_and_get_metrics(self):
        svc = _ConcreteBaseService("base_metrics")

        # Fresh service -> all-zero metrics, healthy.
        metrics = svc.get_metrics()
        self.assertEqual(metrics["calls"], 0)
        self.assertEqual(metrics["errors"], 0)
        self.assertEqual(metrics["average_time"], 0.0)
        self.assertEqual(metrics["error_rate"], 0.0)
        self.assertTrue(svc.is_healthy())

        # One successful and one failed timed operation.
        start = svc._start_operation("op_ok")
        svc._end_operation("op_ok", start, success=True)
        start = svc._start_operation("op_bad")
        svc._end_operation("op_bad", start, success=False)

        metrics = svc.get_metrics()
        self.assertEqual(metrics["calls"], 2)
        self.assertEqual(metrics["errors"], 1)
        self.assertGreaterEqual(metrics["total_time"], 0.0)
        # error_rate derived from observed data: 1 error / 2 calls.
        self.assertEqual(metrics["error_rate"], 0.5)

    def test_is_healthy_false_on_high_error_rate(self):
        svc = _ConcreteBaseService("unhealthy")
        # 2 of 3 calls fail -> error rate 0.66 > 0.5 threshold.
        for success in (False, False, True):
            start = svc._start_operation("op")
            svc._end_operation("op", start, success=success)
        self.assertFalse(svc.is_healthy())

    def test_is_healthy_false_after_cleanup(self):
        svc = _ConcreteBaseService("shutdown")
        self.assertTrue(svc.is_healthy())
        svc.cleanup()
        self.assertTrue(svc._is_shutdown)
        self.assertFalse(svc.is_healthy())

    def test_create_result_with_and_without_metadata(self):
        svc = _ConcreteBaseService("result")

        plain = svc.create_result(success=True, message="ok", data={"x": 1})
        self.assertTrue(plain["success"])
        self.assertEqual(plain["message"], "ok")
        self.assertEqual(plain["data"], {"x": 1})
        self.assertEqual(plain["errors"], [])
        self.assertEqual(plain["service"], "result")
        self.assertIn("timestamp", plain)
        self.assertNotIn("metadata", plain)

        with_meta = svc.create_result(success=False, errors=["boom"], metadata={"k": "v"})
        self.assertFalse(with_meta["success"])
        self.assertEqual(with_meta["errors"], ["boom"])
        self.assertEqual(with_meta["metadata"], {"k": "v"})

    def test_handle_error_no_raise_returns_envelope(self):
        svc = _ConcreteBaseService("handler")
        err = ValueError("kaboom")
        self.expectErrorLog("handler Error")
        result = svc.handle_error(err, "do_thing", context={"a": 1}, raise_error=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "kaboom")
        self.assertIn("kaboom", result["errors"])
        self.assertEqual(result["operation"], "do_thing")

    def test_handle_error_raise_wraps_in_service_error(self):
        svc = _ConcreteBaseService("handler_raise")
        self.expectErrorLog("handler_raise Error")
        with self.assertRaises(ServiceError):
            svc.handle_error(ValueError("nope"), "do_thing", raise_error=True)


class StatelessServiceTests(EnhancedTestCase):
    """Coverage of StatelessService.execute_operation success/error branches."""

    def test_execute_operation_success(self):
        svc = StatelessService("stateless_ok")
        self.assertTrue(svc.validate_configuration())

        def add(a, b):
            return a + b

        self.assertEqual(svc.execute_operation(add, 2, 3), 5)
        metrics = svc.get_metrics()
        self.assertEqual(metrics["calls"], 1)
        self.assertEqual(metrics["errors"], 0)

    def test_execute_operation_error_raises_and_records(self):
        svc = StatelessService("stateless_err")

        def boom():
            raise RuntimeError("stateless failure")

        self.expectErrorLog("stateless_err Error")
        with self.assertRaises(ServiceError):
            svc.execute_operation(boom)

        metrics = svc.get_metrics()
        self.assertEqual(metrics["calls"], 1)
        self.assertEqual(metrics["errors"], 1)


class StatefulServiceTransactionTests(EnhancedTestCase):
    """execute_with_transaction commit/rollback against real Member rows."""

    def test_execute_with_transaction_commit_persists(self):
        svc = StatefulService("stateful_commit")
        self.assertTrue(svc.validate_configuration())

        def make_member():
            member = self.create_test_member(
                first_name="StatefulCommit",
                last_name="Svc",
                email="stateful.commit@verenigingen-test.nl",
            )
            return member.name

        member_name = svc.execute_with_transaction(make_member)
        self.assertTrue(frappe.db.exists("Member", member_name))

        # Savepoint released -> nested transaction state cleared.
        self.assertFalse(svc._transaction_active)
        self.assertIsNone(svc._savepoint_name)

        metrics = svc.get_metrics()
        self.assertEqual(metrics["calls"], 1)
        self.assertEqual(metrics["errors"], 0)

    def test_execute_with_transaction_rollback_undoes_write(self):
        # Create a baseline member OUTSIDE the service transaction so it survives.
        member = self.create_test_member(
            first_name="RollbackBase",
            last_name="Svc",
            email="rollback.base@verenigingen-test.nl",
        )
        original_email = frappe.db.get_value("Member", member.name, "email")

        svc = StatefulService("stateful_rollback")
        new_email = "rollback.changed@verenigingen-test.nl"

        def mutate_then_fail():
            # Non-committed direct write inside the service savepoint.
            frappe.db.set_value("Member", member.name, "email", new_email, update_modified=False)
            # Sanity: change is visible within the same transaction before failure.
            self.assertEqual(frappe.db.get_value("Member", member.name, "email"), new_email)
            raise RuntimeError("deliberate failure to drive rollback")

        self.expectErrorLog("stateful_rollback Error")
        with self.assertRaises(ServiceError):
            svc.execute_with_transaction(mutate_then_fail)

        # Savepoint rolled back -> the field write must be undone.
        self.assertEqual(frappe.db.get_value("Member", member.name, "email"), original_email)

        # Transaction state cleared after rollback.
        self.assertFalse(svc._transaction_active)
        self.assertIsNone(svc._savepoint_name)

        metrics = svc.get_metrics()
        self.assertEqual(metrics["errors"], 1)

    def test_manual_begin_commit_release(self):
        svc = StatefulService("manual_commit")
        svc.begin_transaction()
        self.assertTrue(svc._transaction_active)
        self.assertIsNotNone(svc._savepoint_name)
        # Idempotent: second begin does not replace the active savepoint.
        first_name = svc._savepoint_name
        svc.begin_transaction()
        self.assertEqual(svc._savepoint_name, first_name)

        svc.commit_transaction()
        self.assertFalse(svc._transaction_active)
        self.assertIsNone(svc._savepoint_name)
        # Commit when inactive is a no-op (does not raise).
        svc.commit_transaction()

    def test_manual_begin_rollback(self):
        member = self.create_test_member(
            first_name="ManualRollback",
            last_name="Svc",
            email="manual.rollback@verenigingen-test.nl",
        )
        original_email = frappe.db.get_value("Member", member.name, "email")

        svc = StatefulService("manual_rollback")
        svc.begin_transaction()
        frappe.db.set_value(
            "Member", member.name, "email", "manual.changed@verenigingen-test.nl", update_modified=False
        )
        svc.rollback_transaction()
        self.assertFalse(svc._transaction_active)
        self.assertEqual(frappe.db.get_value("Member", member.name, "email"), original_email)
        # Rollback when inactive is a no-op.
        svc.rollback_transaction()


class APIServicePermissionTests(EnhancedTestCase):
    """validate_permissions / validate_input / format / security-context coverage."""

    def test_validate_permissions_administrator_grant(self):
        svc = APIService("api_admin")
        # Tests run as Administrator -> admin grant branch.
        result = svc.validate_permissions("read", "Member")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["permission_level"], "admin")

    def test_validate_permissions_guest_denied(self):
        svc = APIService("api_guest")
        with self.as_user("Guest"):
            result = svc.validate_permissions("read", "Member")
        self.assertFalse(result["success"])
        self.assertIn("Authentication required", result["message"])

    def test_validate_input_required_fields(self):
        svc = APIService("api_input")
        ok = svc.validate_input({"name": "x", "email": "x@y.nl"}, ["name", "email"])
        self.assertTrue(ok["success"])

        bad = svc.validate_input({"name": "x"}, ["name", "email"])
        self.assertFalse(bad["success"])
        self.assertIn("email", str(bad["errors"]))

    def test_format_api_response_shape(self):
        svc = APIService("api_format")
        resp = svc.format_api_response(True, data={"a": 1}, message="hi")
        self.assertTrue(resp["success"])
        self.assertEqual(resp["data"], {"a": 1})
        self.assertEqual(resp["service"], "api_format")
        self.assertIn("timestamp", resp)
        self.assertEqual(resp["errors"], [])

    def test_get_security_context(self):
        # Under the test runner the request-bound accessors (request_ip /
        # get_request_header) are unbound, so get_security_context() exercises
        # its except-branch fallback. Pin that documented recovery contract:
        # service preserved, user/roles degraded to safe defaults, timestamp set.
        svc = APIService("api_ctx")
        ctx = svc.get_security_context()
        self.assertEqual(ctx["service"], "api_ctx")
        self.assertEqual(ctx["user"], "unknown")
        self.assertEqual(ctx["roles"], [])
        self.assertIn("timestamp", ctx)


class DataServiceTests(EnhancedTestCase):
    """Cache, bulk_operation and safe_query coverage for DataService."""

    def test_cache_enable_disable_clear(self):
        svc = DataService("data_cache")
        self.assertTrue(svc._cache_enabled)
        svc.disable_cache()
        self.assertFalse(svc._cache_enabled)
        svc.enable_cache()
        self.assertTrue(svc._cache_enabled)
        svc._cache["k"] = "v"
        svc.clear_cache()
        self.assertEqual(svc._cache, {})

    def test_cached_query_miss_then_hit(self):
        svc = DataService("data_cached_query")
        calls = {"n": 0}

        def query():
            calls["n"] += 1
            return calls["n"]

        first = svc.cached_query("key1", query)
        second = svc.cached_query("key1", query)
        # Second call served from cache -> query only executed once.
        self.assertEqual(first, second)
        self.assertEqual(calls["n"], 1)

        # With cache disabled, the query runs every time.
        svc.disable_cache()
        svc.cached_query("key2", query)
        svc.cached_query("key2", query)
        self.assertEqual(calls["n"], 3)

    def test_bulk_operation_all_success(self):
        svc = DataService("data_bulk_ok")
        seen = []

        def op(item):
            seen.append(item)

        result = svc.bulk_operation(op, [1, 2, 3, 4, 5], batch_size=2)
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["processed"], 5)
        self.assertEqual(result["data"]["total"], 5)
        self.assertEqual(sorted(seen), [1, 2, 3, 4, 5])

    def test_bulk_operation_batch_failure_collected(self):
        svc = DataService("data_bulk_err")

        def op(item):
            if item == 3:
                raise ValueError("bad item 3")

        # batch_size=2 -> items [1,2] ok, [3,4] fails on 3, [5] ok.
        result = svc.bulk_operation(op, [1, 2, 3, 4, 5], batch_size=2)
        self.assertFalse(result["success"])
        self.assertTrue(len(result["errors"]) >= 1)
        self.assertIn("bad item 3", str(result["errors"]))
        # Items 1,2 (batch 1) and 5 (batch 3) processed; batch 2 rolled back.
        self.assertEqual(result["data"]["processed"], 3)

    def test_field_validation_toggle_and_safe_query(self):
        svc = DataService("data_safe_query")
        member = self.create_test_member(
            first_name="SafeQuery",
            last_name="Svc",
            email="safe.query@verenigingen-test.nl",
        )
        # With validation enabled, querying valid fields must succeed.
        rows = svc.safe_query("Member", filters={"name": member.name}, fields=["name", "email"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], member.name)

        # Disable field validation -> validate_query_fields short-circuits.
        svc.disable_field_validation()
        self.assertFalse(svc._field_validation_enabled)
        result = svc.validate_query_fields("Member", {"fields": ["name"]})
        self.assertTrue(result["success"])
        svc.enable_field_validation()
        self.assertTrue(svc._field_validation_enabled)

    def test_safe_get_doc(self):
        svc = DataService("data_safe_doc")
        member = self.create_test_member(
            first_name="SafeDoc",
            last_name="Svc",
            email="safe.doc@verenigingen-test.nl",
        )
        full = svc.safe_get_doc("Member", member.name)
        self.assertEqual(full["name"], member.name)

    def test_data_service_cleanup_clears_cache(self):
        svc = DataService("data_cleanup")
        svc._cache["k"] = "v"
        svc.cleanup()
        self.assertTrue(svc._is_shutdown)
        self.assertEqual(svc._cache, {})


class ServiceMetricsTests(EnhancedTestCase):
    """ServiceMetrics record/summary/detailed/reset/cleanup/memory coverage."""

    def test_summary_derived_from_recorded_operations(self):
        m = ServiceMetrics("svc_summary")
        m.record_operation("op_a", 0.10, success=True)
        m.record_operation("op_a", 0.20, success=True)
        m.record_operation("op_b", 0.30, success=False)

        summary = m.get_summary()
        self.assertEqual(summary["call_count"], 3)
        self.assertEqual(summary["error_count"], 1)
        self.assertAlmostEqual(summary["total_time"], 0.60, places=6)
        self.assertAlmostEqual(summary["average_response_time"], 0.20, places=6)
        self.assertAlmostEqual(summary["error_rate"], 1 / 3, places=6)
        self.assertEqual(summary["operations"], 2)

    def test_detailed_metrics_percentiles_and_breakdown(self):
        m = ServiceMetrics("svc_detail")
        for i in range(10):
            m.record_operation("op", 0.01 * (i + 1), success=(i != 0))

        detailed = m.get_detailed_metrics()
        # Durations are 0.01..0.10; sorted n=10 -> p50=index 5=0.06, p95/p99=index 9=0.10.
        pct = detailed["percentiles"]
        self.assertAlmostEqual(pct["p50"], 0.06, places=6)
        self.assertAlmostEqual(pct["p95"], 0.10, places=6)
        self.assertAlmostEqual(pct["p99"], 0.10, places=6)
        op = detailed["operations"]["op"]
        self.assertEqual(op["count"], 10)
        self.assertEqual(op["errors"], 1)
        # min/max derived from the recorded durations.
        self.assertAlmostEqual(op["min_time"], 0.01, places=6)
        self.assertAlmostEqual(op["max_time"], 0.10, places=6)

    def test_detailed_metrics_empty_percentiles(self):
        m = ServiceMetrics("svc_detail_empty")
        detailed = m.get_detailed_metrics()
        self.assertEqual(detailed["percentiles"], {"p50": 0, "p95": 0, "p99": 0})
        self.assertEqual(detailed["operations"], {})

    def test_reset_metrics(self):
        m = ServiceMetrics("svc_reset")
        m.record_operation("op", 0.05, success=True)
        self.assertEqual(m.call_count, 1)
        m.reset_metrics()
        self.assertEqual(m.call_count, 0)
        self.assertEqual(m.error_count, 0)
        self.assertEqual(m.total_time, 0.0)
        self.assertEqual(len(m.operation_metrics), 0)
        self.assertEqual(len(m.response_times), 0)

    def test_max_operations_cap_evicts_lru(self):
        m = ServiceMetrics("svc_cap", max_history=1000, max_operations=3)
        for i in range(20):
            m.record_operation(f"op_{i}", 0.001, success=True)
        # Cap enforced -> tracked operation set never exceeds the configured max.
        self.assertLessEqual(len(m.operation_metrics), 3)
        usage = m.get_memory_usage()
        self.assertLessEqual(usage["operation_count"], 3)
        self.assertTrue(usage["memory_efficient"])

    def test_cleanup_old_operations_idle_eviction(self):
        m = ServiceMetrics("svc_idle", max_history=1000, max_operations=100)
        m.record_operation("stale_op", 0.01, success=True)
        m.record_operation("fresh_op", 0.01, success=True)
        # Force "stale_op" past the 24h idle threshold.
        m._operation_access_times["stale_op"] = time.time() - (25 * 3600)
        m._cleanup_old_operations()
        self.assertNotIn("stale_op", m.operation_metrics)
        self.assertIn("fresh_op", m.operation_metrics)

    def test_memory_usage_reports_thresholds(self):
        m = ServiceMetrics("svc_mem", max_history=10, max_operations=5)
        usage = m.get_memory_usage()
        self.assertEqual(usage["max_operations"], 5)
        self.assertEqual(usage["max_history"], 10)
        self.assertTrue(usage["memory_efficient"])

        # Cross the 80% efficiency boundary: 5 distinct ops (>= 5*0.8=4) flips it.
        for i in range(5):
            m.record_operation(f"op_{i}", 0.001, success=True)
        self.assertFalse(m.get_memory_usage()["memory_efficient"])


class MetricsCollectorTests(EnhancedTestCase):
    """MetricsCollector aggregation coverage."""

    def test_get_or_create_and_record(self):
        collector = MetricsCollector()
        m1 = collector.get_service_metrics("svc_x")
        m2 = collector.get_service_metrics("svc_x")
        self.assertIs(m1, m2)

        collector.record_service_operation("svc_x", "op", 0.10, success=True)
        collector.record_service_operation("svc_y", "op", 0.20, success=False)

        all_metrics = collector.get_all_metrics()
        self.assertIn("svc_x", all_metrics)
        self.assertIn("svc_y", all_metrics)

    def test_aggregated_metrics_empty(self):
        collector = MetricsCollector()
        agg = collector.get_aggregated_metrics()
        self.assertEqual(agg["total_services"], 0)
        self.assertEqual(agg["total_calls"], 0)
        self.assertEqual(agg["overall_error_rate"], 0)

    def test_aggregated_metrics_populated(self):
        collector = MetricsCollector()
        collector.record_service_operation("a", "op", 0.10, success=True)
        collector.record_service_operation("a", "op", 0.10, success=False)
        collector.record_service_operation("b", "op", 0.20, success=True)

        agg = collector.get_aggregated_metrics()
        self.assertEqual(agg["total_services"], 2)
        self.assertEqual(agg["total_calls"], 3)
        self.assertEqual(agg["total_errors"], 1)
        self.assertAlmostEqual(agg["overall_error_rate"], 1 / 3, places=6)
        self.assertEqual(set(agg["services"]), {"a", "b"})

    def test_reset_all_metrics(self):
        collector = MetricsCollector()
        collector.record_service_operation("a", "op", 0.10, success=True)
        collector.reset_all_metrics()
        self.assertEqual(collector.get_service_metrics("a").call_count, 0)


class HealthMonitorTests(EnhancedTestCase):
    """HealthMonitor health-status branch coverage."""

    def test_unhealthy_on_high_error_rate(self):
        collector = MetricsCollector()
        monitor = HealthMonitor(collector)
        # All failures -> error rate 1.0 > 5% threshold.
        for _ in range(5):
            collector.record_service_operation("bad_svc", "op", 0.10, success=False)

        health = monitor.check_service_health("bad_svc")
        self.assertFalse(health["success"])
        self.assertEqual(health["status"], "unhealthy")
        self.assertTrue(any("error rate" in issue for issue in health["data"]["issues"]))

    def test_slow_response_time_flagged(self):
        collector = MetricsCollector()
        monitor = HealthMonitor(collector)
        # Single successful but very slow op (> 5s threshold), high throughput.
        collector.record_service_operation("slow_svc", "op", 10.0, success=True)
        health = monitor.check_service_health("slow_svc")
        self.assertEqual(health["status"], "unhealthy")
        self.assertTrue(any("response time" in issue for issue in health["data"]["issues"]))

    def test_check_all_and_system_summary_degraded(self):
        collector = MetricsCollector()
        monitor = HealthMonitor(collector)
        # One bad service -> degraded (not critical, since others may be healthy).
        for _ in range(5):
            collector.record_service_operation("svc_bad", "op", 0.10, success=False)

        all_reports = monitor.check_all_services_health()
        self.assertIn("svc_bad", all_reports)

        summary = monitor.get_system_health_summary()
        self.assertIn(summary["status"], ("degraded", "critical"))
        self.assertEqual(summary["data"]["total_services"], len(all_reports))

    def test_system_summary_no_services(self):
        collector = MetricsCollector()
        monitor = HealthMonitor(collector)
        summary = monitor.get_system_health_summary()
        self.assertEqual(summary["overall_status"], "no_services")
        self.assertEqual(summary["total_services"], 0)


class PerformanceProfilerTests(EnhancedTestCase):
    """PerformanceProfiler start/end/get/clear coverage."""

    def test_profile_lifecycle(self):
        profiler = PerformanceProfiler()
        pid = profiler.start_profile("svc", "op")
        self.assertIn(pid, profiler.profiles)
        # Results exclude unfinished profiles.
        self.assertEqual(profiler.get_profile_results(), [])

        profiler.end_profile(pid, success=True, details={"k": "v"})
        results = profiler.get_profile_results()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"])
        self.assertEqual(results[0]["details"], {"k": "v"})
        self.assertIsNotNone(results[0]["duration"])

    def test_get_results_filtered_by_service(self):
        profiler = PerformanceProfiler()
        p1 = profiler.start_profile("svc_a", "op")
        p2 = profiler.start_profile("svc_b", "op")
        profiler.end_profile(p1)
        profiler.end_profile(p2)

        a_only = profiler.get_profile_results("svc_a")
        self.assertEqual(len(a_only), 1)
        self.assertEqual(a_only[0]["service_name"], "svc_a")

    def test_end_profile_unknown_id_is_noop(self):
        profiler = PerformanceProfiler()
        profiler.end_profile("does-not-exist", success=True)  # must not raise
        self.assertEqual(profiler.get_profile_results(), [])

    def test_clear_profiles_all_and_by_service(self):
        profiler = PerformanceProfiler()
        p1 = profiler.start_profile("svc_a", "op")
        p2 = profiler.start_profile("svc_b", "op")
        profiler.end_profile(p1)
        profiler.end_profile(p2)

        profiler.clear_profiles("svc_a")
        remaining = profiler.get_profile_results()
        self.assertTrue(all(r["service_name"] != "svc_a" for r in remaining))

        profiler.clear_profiles()
        self.assertEqual(profiler.profiles, {})


class GlobalAccessorTests(EnhancedTestCase):
    """Module-level singleton accessors and convenience functions."""

    def test_singleton_accessors(self):
        self.assertIs(get_metrics_collector(), get_metrics_collector())
        self.assertIs(get_health_monitor(), get_health_monitor())
        self.assertIs(get_profiler(), get_profiler())
        # Health monitor wraps the global collector.
        self.assertIs(get_health_monitor().metrics_collector, get_metrics_collector())

    def test_record_operation_and_get_service_health(self):
        record_operation("global_svc", "op", 0.10, success=True)
        health = get_service_health("global_svc")
        self.assertEqual(health["service_name"], "global_svc")
        self.assertIn(health["status"], ("healthy", "unhealthy", "error"))
        # The recorded operation is reflected in the health metrics.
        self.assertGreaterEqual(health["data"]["metrics"]["call_count"], 1)

    def test_get_system_health(self):
        record_operation("global_svc2", "op", 0.10, success=True)
        summary = get_system_health()
        self.assertIn(summary["status"], ("healthy", "degraded", "critical"))
        # The service we just recorded is included in the system-wide report.
        self.assertIn("global_svc2", get_metrics_collector().service_metrics)
