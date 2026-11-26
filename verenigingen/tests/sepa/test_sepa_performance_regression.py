#!/usr/bin/env python3
"""
Performance regression tests for SEPA optimizations
Ensures optimizations maintain performance benefits over time
"""

import time
import frappe
from frappe.utils import today, add_days
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSEPAPerformanceRegression(VereningingenTestCase):
    """Performance regression tests for SEPA optimizations"""

    def setUp(self):
        super().setUp()
        self.performance_thresholds = {
            "mandate_batch_lookup": 0.5,  # seconds
            "config_retrieval": 0.1,  # seconds
            "invoice_lookup": 2.0,  # seconds
            "coverage_verification": 5.0,  # seconds
        }

    def measure_execution_time(self, operation_name, operation_func, *args, **kwargs):
        """Measure execution time of an operation"""
        start_time = time.time()
        result = operation_func(*args, **kwargs)
        execution_time = time.time() - start_time

        threshold = self.performance_thresholds.get(operation_name, 1.0)

        print(f"  {operation_name}: {execution_time:.3f}s (threshold: {threshold}s)")

        self.assertLess(
            execution_time,
            threshold,
            f"{operation_name} took {execution_time:.3f}s, exceeding threshold of {threshold}s",
        )

        return result, execution_time

    def test_mandate_service_performance(self):
        """Test mandate service performance benchmarks"""
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import get_sepa_mandate_service

        service = get_sepa_mandate_service()

        # Test batch mandate lookup performance
        test_members = [f"TEST-MEM-{i:03d}" for i in range(1, 21)]  # 20 test members

        result, exec_time = self.measure_execution_time(
            "mandate_batch_lookup", service.get_active_mandate_batch, test_members
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), len(test_members))

        # Test cache effectiveness (second call should be faster)
        start_time = time.time()
        cached_result = service.get_active_mandate_batch(test_members[:10])  # Subset should be cached
        cached_time = time.time() - start_time

        print(f"  Cached lookup: {cached_time:.3f}s")
        # Cached lookup should be significantly faster
        self.assertLess(cached_time, exec_time / 2, "Cached lookup should be at least 2x faster")

    def test_configuration_manager_performance(self):
        """Test configuration manager performance"""
        from verenigingen.verenigingen_payments.utils.sepa_config_manager import get_sepa_config_manager

        manager = get_sepa_config_manager()

        # Test complete configuration retrieval
        result, exec_time = self.measure_execution_time("config_retrieval", manager.get_complete_config)

        self.assertIsInstance(result, dict)
        self.assertGreaterEqual(len(result), 6)  # Should have at least 6 sections

        # Test cached configuration (should be much faster)
        start_time = time.time()
        cached_result = manager.get_complete_config()
        cached_time = time.time() - start_time

        print(f"  Cached config: {cached_time:.3f}s")
        self.assertLess(cached_time, 0.01, "Cached config should be < 10ms")

    def test_sepa_processor_performance(self):
        """Test Enhanced SEPA Processor performance"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor

        processor = SEPAProcessor()

        # Test invoice lookup performance
        result, exec_time = self.measure_execution_time(
            "invoice_lookup", processor.get_existing_unpaid_sepa_invoices, today()
        )

        self.assertIsInstance(result, list)

        # Test coverage verification performance
        result, exec_time = self.measure_execution_time(
            "coverage_verification", processor.verify_invoice_coverage, today()
        )

        self.assertIsInstance(result, dict)
        self.assertIn("total_checked", result)

    def test_sequence_type_batch_leaves_out_undeterminable_pairs(self):
        """#3077: since #2716 a pair whose type cannot be determined has NO entry.

        This used to be a timing test over 20 pairs of non-existent mandates that expected 20
        entries. Those pairs now take the error path (one Error Log row each), so a timing
        bound over them measures nothing about the real path; it is a correctness test now.
        The control mandate has a Collected usage, so its real type (RCUR) differs from the
        FRST guess an undeterminable pair used to get.
        """
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            create_mandate_usage_record,
        )
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import SEPAMandateService

        service = SEPAMandateService()  # fresh instance: the singleton's cache is process-wide

        missing_pairs = [(f"MANDATE-{i}", f"INV-{i}") for i in range(1, 21)]
        self.expectErrorLog("Error determining sequence type")
        self.assertEqual(service.get_sequence_types_batch(missing_pairs), {})

        mandate = self.create_test_sepa_mandate(scenario="normal")
        usage_name = create_mandate_usage_record(
            mandate_name=mandate.name,
            reference_doctype="Sales Invoice",
            reference_name=f"PRIOR-{frappe.generate_hash(length=8)}",
            amount=10,
            sequence_type="FRST",
        )
        # Probe shortcut: these db_set writes stand in for the batch-collection flow (the real
        # "Collected" writer is in batch_processing_service.py); the flow itself is not driven here.
        for row in frappe.get_doc("SEPA Mandate", mandate.name).usage_history:
            if row.name == usage_name:
                row.db_set("status", "Collected", update_modified=False)
                row.db_set("processing_date", today(), update_modified=False)
        real_key = f"{mandate.name}:INV-REAL-{frappe.generate_hash(length=6)}"
        real_pair = (mandate.name, real_key.split(":", 1)[1])

        result = service.get_sequence_types_batch(missing_pairs + [real_pair])

        # A Collected usage on the mandate and sign_date not after it (no renewal) -> RCUR.
        self.assertEqual(result, {real_key: "RCUR"})

    def test_database_query_performance(self):
        """Test database query performance with indexes"""

        # Test Sales Invoice query with custom fields (should use indexes)
        start_time = time.time()
        invoices = frappe.db.sql(
            """
            SELECT si.name, si.membership_dues_schedule_display
            FROM `tabSales Invoice` si
            WHERE si.docstatus = 1
              AND si.status IN ('Unpaid', 'Overdue')
              AND si.membership_dues_schedule_display IS NOT NULL
            LIMIT 100
        """,
            as_dict=True,
        )
        query_time = time.time() - start_time

        print(f"  Sales Invoice query: {query_time:.3f}s")
        self.assertLess(query_time, 1.0, "Sales Invoice query should be fast with indexes")

        # Test Membership Dues Schedule query (should use indexes)
        start_time = time.time()
        schedules = frappe.db.sql(
            """
            SELECT name, member, status, payment_terms_template
            FROM `tabMembership Dues Schedule`
            WHERE status = 'Active'
              AND auto_generate = 1
              AND payment_terms_template = 'SEPA Direct Debit'
            LIMIT 100
        """,
            as_dict=True,
        )
        query_time = time.time() - start_time

        print(f"  Dues Schedule query: {query_time:.3f}s")
        self.assertLess(query_time, 0.5, "Dues Schedule query should be fast with indexes")

        # Test SEPA Mandate query (should use indexes)
        start_time = time.time()
        mandates = frappe.db.sql(
            """
            SELECT name, member, status, iban
            FROM `tabSEPA Mandate`
            WHERE status = 'Active'
              AND iban IS NOT NULL
            LIMIT 100
        """,
            as_dict=True,
        )
        query_time = time.time() - start_time

        print(f"  SEPA Mandate query: {query_time:.3f}s")
        self.assertLess(query_time, 0.5, "SEPA Mandate query should be fast with indexes")

    def test_error_handler_performance(self):
        """Test error handler performance doesn't add significant overhead"""
        from verenigingen.verenigingen_payments.utils.sepa_error_handler import get_sepa_error_handler

        handler = get_sepa_error_handler()

        # Test a simple successful operation
        def simple_operation():
            return "success"

        # Measure execution time with error handler
        start_time = time.time()
        result = handler.execute_with_retry(simple_operation)
        with_handler_time = time.time() - start_time

        # Measure execution time without error handler
        start_time = time.time()
        direct_result = simple_operation()
        direct_time = time.time() - start_time

        print(f"  With error handler: {with_handler_time:.3f}s")
        print(f"  Direct execution: {direct_time:.3f}s")
        print(f"  Overhead: {(with_handler_time - direct_time) * 1000:.1f}ms")

        # Error handler should add minimal overhead (< 10ms)
        overhead = with_handler_time - direct_time
        self.assertLess(overhead, 0.01, "Error handler should add < 10ms overhead")

        # Results should be equivalent
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], direct_result)

    def test_api_endpoint_performance(self):
        """The config API is served from the manager's cache after the first read.

        Asserted structurally, not against a wall clock (#3085): the first call in a
        process measured 2.8s on test_site_3 (imports, lazy first-use work) while a
        call after clear_cache() measured ~25ms, so a 0.2s bound timed the process
        warm-up and not the cache.
        """
        from verenigingen.verenigingen_payments.utils.sepa_config_manager import (
            get_sepa_config,
            get_sepa_config_manager,
        )
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import (
            get_sepa_cache_stats,
            get_sepa_mandate_service,
        )

        manager = get_sepa_config_manager()
        # Populate first: the singleton starts empty, so clearing an empty cache proves nothing.
        get_sepa_config()
        self.assertGreater(manager.get_cache_info()["total_cached_items"], 0)
        manager.clear_cache()
        self.assertEqual(manager.get_cache_info()["total_cached_items"], 0)

        first = get_sepa_config()
        self.assertEqual(set(first), set(manager.get_complete_config()))
        self.assertGreaterEqual(manager.get_cache_info()["total_cached_items"], 2)

        # A second read must hand back the cached section object, not rebuild it.
        cached_section = manager._settings_cache["company_sepa"]
        second = get_sepa_config()
        self.assertIs(second["company_sepa"], cached_section)
        self.assertEqual(second, first)

        # A section request goes through the same cache.
        self.assertIs(get_sepa_config(section="company_sepa"), cached_section)

        # Mandate service API reports the real cache sizes.
        service = get_sepa_mandate_service()
        self.assertEqual(
            get_sepa_cache_stats(),
            {
                "mandate_cache_size": len(service._mandate_cache),
                "sequence_cache_size": len(service._sequence_cache),
                "total_cached_items": len(service._mandate_cache) + len(service._sequence_cache),
            },
        )

    def test_memory_usage_stability(self):
        """Test that optimizations don't cause memory leaks"""
        import psutil
        import os

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Perform multiple operations to test for memory leaks
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import get_sepa_mandate_service
        from verenigingen.verenigingen_payments.utils.sepa_config_manager import get_sepa_config_manager

        service = get_sepa_mandate_service()
        manager = get_sepa_config_manager()

        # Perform 100 operations
        for i in range(100):
            test_members = [f"TEST-{i}-{j}" for j in range(10)]
            service.get_active_mandate_batch(test_members)
            manager.get_complete_config()

            # Clear caches periodically to simulate real usage
            if i % 25 == 0:
                service.clear_cache()
                manager.clear_cache()

        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory

        print(f"  Initial memory: {initial_memory:.1f}MB")
        print(f"  Final memory: {final_memory:.1f}MB")
        print(f"  Memory increase: {memory_increase:.1f}MB")

        # Memory increase should be reasonable (< 50MB for 1000 operations)
        self.assertLess(
            memory_increase, 50, f"Memory increased by {memory_increase:.1f}MB, possible memory leak"
        )

    def test_concurrent_access_performance(self):
        """Test performance under concurrent access (simulated)"""
        import threading
        import time

        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import get_sepa_mandate_service

        results = []
        site = frappe.local.site

        def worker_thread(thread_id):
            # Each thread needs its OWN Frappe DB connection: frappe.db is
            # thread-local, so a spawned thread that uses the parent's connection
            # raises "object is not bound". Initialize + connect per thread.
            frappe.init(site=site)
            frappe.connect()
            try:
                service = get_sepa_mandate_service()
                start_time = time.time()
                test_members = [f"THREAD-{thread_id}-{i}" for i in range(5)]
                service.get_active_mandate_batch(test_members)
                execution_time = time.time() - start_time
                results.append(execution_time)
            finally:
                frappe.destroy()

        # Create 5 concurrent threads
        threads = []
        start_time = time.time()

        for i in range(5):
            thread = threading.Thread(target=worker_thread, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        total_time = time.time() - start_time
        avg_thread_time = sum(results) / len(results)

        print(f"  Total concurrent time: {total_time:.3f}s")
        print(f"  Average thread time: {avg_thread_time:.3f}s")

        # Concurrent access shouldn't be significantly slower than sequential
        self.assertLess(total_time, 2.0, "Concurrent access should complete quickly")
        self.assertLess(avg_thread_time, 1.0, "Individual thread performance should be good")


def run_performance_tests():
    """Run all performance regression tests"""
    import unittest

    print("🚀 Running SEPA Performance Regression Tests")
    print("=" * 60)

    # Create test suite
    suite = unittest.TestSuite()
    test_class = TestSEPAPerformanceRegression

    # Add all test methods
    for method_name in dir(test_class):
        if method_name.startswith("test_"):
            suite.addTest(test_class(method_name))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("✅ All performance regression tests passed!")
        print("🚀 SEPA optimizations are performing well!")
    else:
        print("❌ Some performance regression tests failed.")
        print("⚠️  Performance may have regressed - investigate failing tests.")

    return result.wasSuccessful()


if __name__ == "__main__":
    # Run performance tests when executed directly
    success = run_performance_tests()
    exit(0 if success else 1)
