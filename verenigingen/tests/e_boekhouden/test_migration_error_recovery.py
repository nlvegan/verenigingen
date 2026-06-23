"""
Coverage tests for verenigingen/utils/migration/migration_error_recovery.py

Covers the pure error-handling machinery: MigrationError serialization, the
exponential-backoff RetryStrategy, the @with_retry decorator (retry-then-succeed
and retry-then-raise), and MigrationErrorRecovery's error logging / analysis /
recommendations against a real saved E-Boekhouden Migration document. log_error
writes a real error_log summary to the migration doc via db.set_value.

Run with:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_error_recovery
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.migration.migration_error_recovery import (
    MigrationError,
    MigrationErrorRecovery,
    RetryStrategy,
    with_retry,
)


def _persist_company(name="ErrRecovery Co", abbr="ERCO"):
    if frappe.db.exists("Company", name):
        return name
    company = frappe.new_doc("Company")
    company.company_name = name
    company.abbr = abbr
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return name


def _make_migration_doc(company):
    doc = frappe.new_doc("E-Boekhouden Migration")
    doc.migration_name = "Error Recovery Coverage"
    doc.company = company
    doc.migration_status = "Draft"
    doc.date_from = "2024-01-01"
    doc.date_to = "2024-12-31"
    doc.insert(ignore_permissions=True)
    return doc


class TestMigrationError(EnhancedTestCase):
    def test_to_dict_truncates_long_message(self):
        err = MigrationError("ValueError", "x" * 1000, record_data={"a": 1})
        d = err.to_dict()
        self.assertEqual(d["error_type"], "ValueError")
        self.assertLessEqual(len(d["message"]), 500)
        self.assertEqual(d["record_data"], {"a": 1})
        self.assertIn("timestamp", d)


class TestRetryStrategy(EnhancedTestCase):
    def test_exponential_backoff_grows(self):
        strat = RetryStrategy(initial_delay=1, backoff_factor=2, max_delay=60)
        self.assertEqual(strat.get_delay(1), 1)  # 1 * 2^0
        self.assertEqual(strat.get_delay(2), 2)  # 1 * 2^1
        self.assertEqual(strat.get_delay(3), 4)  # 1 * 2^2

    def test_delay_is_capped_at_max(self):
        strat = RetryStrategy(initial_delay=10, backoff_factor=10, max_delay=15)
        self.assertEqual(strat.get_delay(5), 15)


class TestWithRetryDecorator(EnhancedTestCase):
    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        # initial_delay=0 keeps the test fast while still exercising the retry loop.
        @with_retry(retry_strategy=RetryStrategy(max_retries=3, initial_delay=0))
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("transient")
            return "ok"

        self.assertEqual(flaky(), "ok")
        self.assertEqual(calls["n"], 2)

    def test_exhausts_retries_then_raises(self):
        calls = {"n": 0}

        @with_retry(retry_strategy=RetryStrategy(max_retries=2, initial_delay=0))
        def always_fail():
            calls["n"] += 1
            raise ValueError("permanent")

        with self.assertRaises(ValueError):
            always_fail()
        self.assertEqual(calls["n"], 2)

    def test_error_handler_invoked_per_attempt(self):
        seen = []

        @with_retry(
            retry_strategy=RetryStrategy(max_retries=2, initial_delay=0),
            error_handler=lambda e: seen.append(e.error_type),
        )
        def fail():
            raise KeyError("nope")

        with self.assertRaises(KeyError):
            fail()
        self.assertEqual(seen, ["KeyError", "KeyError"])


class _RecoveryBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_company()

    def setUp(self):
        super().setUp()
        self.migration = _make_migration_doc(self.company)
        self.recovery = MigrationErrorRecovery(self.migration)


class TestErrorLogging(_RecoveryBase):
    def test_log_error_appends_and_updates_doc(self):
        # Regression: _update_migration_error_log used to also write a phantom
        # "failed_record_count" column, raising OperationalError 1054 which the
        # surrounding try/except swallowed -> the error_log was NEVER persisted.
        # The fix writes only the real error_log field, so it persists for real.
        with self.assertNoErrorLog():
            self.recovery.log_error(ValueError("bad row"), record_data={"id": 7})
        self.assertEqual(len(self.recovery.error_log), 1)
        self.assertEqual(len(self.recovery.failed_records), 1)
        stored_error_log = frappe.db.get_value("E-Boekhouden Migration", self.migration.name, "error_log")
        self.assertIn("Total Errors", stored_error_log)
        self.assertIn("Failed Records: 1", stored_error_log)

    def test_error_summary_is_interpolated(self):
        # Regression: summary lines were missing the f-prefix and emitted literal
        # "{len(self.failed_records)}".
        self.recovery.log_error(ValueError("dup key"), record_data={"id": 1})
        summary = self.recovery._create_error_summary()
        self.assertIn("Failed Records: 1", summary)
        self.assertNotIn("{len(", summary)

    def test_error_without_record_data_not_added_to_failed_records(self):
        self.recovery.log_error(RuntimeError("global failure"))
        self.assertEqual(len(self.recovery.error_log), 1)
        self.assertEqual(len(self.recovery.failed_records), 0)


class TestErrorAnalysis(_RecoveryBase):
    def test_analyze_errors_classifies_patterns(self):
        self.recovery.log_error(Exception("Duplicate entry detected"))
        self.recovery.log_error(Exception("validation failed on field"))
        self.recovery.log_error(Exception("connection timeout to host"))
        self.recovery.log_error(Exception("permission denied"))
        self.recovery.log_error(Exception("something weird"))

        analysis = self.recovery._analyze_errors()
        patterns = analysis["error_patterns"]
        self.assertEqual(patterns["Duplicate Entry"], 1)
        self.assertEqual(patterns["Validation Error"], 1)
        self.assertEqual(patterns["Connection/Timeout"], 1)
        self.assertEqual(patterns["Permission Error"], 1)
        self.assertEqual(patterns["Other"], 1)

    def test_recommendations_for_many_connection_errors(self):
        for _ in range(6):
            self.recovery.log_error(Exception("connection refused"))
        recs = self.recovery._get_recovery_recommendations()
        priorities = {r["priority"] for r in recs}
        self.assertIn("high", priorities)

    def test_permission_errors_yield_critical_recommendation(self):
        self.recovery.log_error(Exception("permission denied for user"))
        recs = self.recovery._get_recovery_recommendations()
        self.assertIn("critical", [r["priority"] for r in recs])

    def test_recovery_report_summary_counts(self):
        self.recovery.log_error(Exception("validation error"), record_data={"a": 1})
        self.recovery.add_to_retry_queue({"b": 2})
        with self.assertNoErrorLog():
            report = self.recovery.create_recovery_report()
        self.assertEqual(report["summary"]["total_errors"], 1)
        self.assertEqual(report["summary"]["failed_records"], 1)
        self.assertEqual(report["summary"]["retry_queue_size"], 1)
        self.assertEqual(report["summary"]["pending_retries"], 1)


class TestRetryQueue(_RecoveryBase):
    def test_process_retry_queue_success(self):
        self.recovery.add_to_retry_queue({"id": 1})
        self.recovery.add_to_retry_queue({"id": 2})

        with self.assertNoErrorLog():
            results = self.recovery.process_retry_queue(
                lambda record: {"success": True},
                retry_strategy=RetryStrategy(max_retries=1, initial_delay=0),
            )
        self.assertEqual(results["successful"], 2)
        self.assertEqual(results["failed"], 0)
        self.assertTrue(all(r["status"] == "success" for r in self.recovery.retry_queue))

    def test_process_retry_queue_failure_moves_to_failed_records(self):
        self.recovery.add_to_retry_queue({"id": 99})

        def always_fail(record):
            raise RuntimeError("still broken")

        results = self.recovery.process_retry_queue(
            always_fail, retry_strategy=RetryStrategy(max_retries=1, initial_delay=0)
        )
        self.assertEqual(results["failed"], 1)
        self.assertEqual(self.recovery.retry_queue[0]["status"], "failed")
        # retry_count reached max -> record moved to failed_records.
        self.assertEqual(len(self.recovery.failed_records), 1)


if __name__ == "__main__":
    unittest.main()
