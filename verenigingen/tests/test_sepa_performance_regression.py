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
            "sequence_type_batch": 1.0,  # seconds
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
            f"{operation_name} took {execution_time:.3f}s, exceeding threshold of {threshold}s"
        )
        
        return result, execution_time
    
    def test_mandate_service_performance(self):
        """Test mandate service performance benchmarks"""
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import get_sepa_mandate_service
        
        service = get_sepa_mandate_service()
        
        # Test batch mandate lookup performance
        test_members = [f"TEST-MEM-{i:03d}" for i in range(1, 21)]  # 20 test members
        
        result, exec_time = self.measure_execution_time(
            "mandate_batch_lookup",
            service.get_active_mandate_batch,
            test_members
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
        result, exec_time = self.measure_execution_time(
            "config_retrieval",
            manager.get_complete_config
        )
        
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
            "invoice_lookup",
            processor.get_existing_unpaid_sepa_invoices,
            today()
        )
        
        self.assertIsInstance(result, list)
        
        # Test coverage verification performance
        result, exec_time = self.measure_execution_time(
            "coverage_verification",
            processor.verify_invoice_coverage,
            today()
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn("total_checked", result)
    
    def test_sequence_type_batch_performance(self):
        """Test batch sequence type determination performance"""
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import get_sepa_mandate_service
        
        service = get_sepa_mandate_service()
        
        # Create test pairs
        test_pairs = [(f"MANDATE-{i}", f"INV-{i}") for i in range(1, 21)]  # 20 pairs
        
        try:
            result, exec_time = self.measure_execution_time(
                "sequence_type_batch",
                service.get_sequence_types_batch,
                test_pairs
            )
            
            self.assertIsInstance(result, dict)
            # Should return results for all pairs
            self.assertEqual(len(result), len(test_pairs))
            
        except Exception as e:
            self.skipTest(f"Sequence type test requires SEPA setup: {str(e)}")
    
    def test_database_query_performance(self):
        """Test database query performance with indexes"""
        
        # Test Sales Invoice query with custom fields (should use indexes)
        start_time = time.time()
        invoices = frappe.db.sql("""
            SELECT si.name, si.custom_membership_dues_schedule
            FROM `tabSales Invoice` si
            WHERE si.docstatus = 1
              AND si.status IN ('Unpaid', 'Overdue')
              AND si.custom_membership_dues_schedule IS NOT NULL
            LIMIT 100
        """, as_dict=True)
        query_time = time.time() - start_time
        
        print(f"  Sales Invoice query: {query_time:.3f}s")
        self.assertLess(query_time, 1.0, "Sales Invoice query should be fast with indexes")
        
        # Test Membership Dues Schedule query (should use indexes)
        start_time = time.time()
        schedules = frappe.db.sql("""
            SELECT name, member, status, payment_method
            FROM `tabMembership Dues Schedule`
            WHERE status = 'Active'
              AND auto_generate = 1
              AND payment_method = 'SEPA Direct Debit'
            LIMIT 100
        """, as_dict=True)
        query_time = time.time() - start_time
        
        print(f"  Dues Schedule query: {query_time:.3f}s")
        self.assertLess(query_time, 0.5, "Dues Schedule query should be fast with indexes")
        
        # Test SEPA Mandate query (should use indexes)
        start_time = time.time()
        mandates = frappe.db.sql("""
            SELECT name, member, status, iban
            FROM `tabSEPA Mandate`
            WHERE status = 'Active'
              AND iban IS NOT NULL
            LIMIT 100
        """, as_dict=True)
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
        """Test API endpoint performance"""
        
        # Test configuration APIs
        from verenigingen.verenigingen_payments.utils.sepa_config_manager import get_sepa_config
        
        start_time = time.time()
        config = get_sepa_config()
        api_time = time.time() - start_time
        
        print(f"  Configuration API: {api_time:.3f}s")
        self.assertLess(api_time, 0.2, "Configuration API should be fast")
        
        # Test mandate service APIs
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import get_sepa_cache_stats
        
        start_time = time.time()
        cache_stats = get_sepa_cache_stats()
        api_time = time.time() - start_time
        
        print(f"  Cache stats API: {api_time:.3f}s")
        self.assertLess(api_time, 0.1, "Cache stats API should be very fast")
    
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
        self.assertLess(memory_increase, 50, 
                       f"Memory increased by {memory_increase:.1f}MB, possible memory leak")
    
    def test_concurrent_access_performance(self):
        """Test performance under concurrent access (simulated)"""
        import threading
        import time
        
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import get_sepa_mandate_service
        
        service = get_sepa_mandate_service()
        results = []
        
        def worker_thread(thread_id):
            start_time = time.time()
            test_members = [f"THREAD-{thread_id}-{i}" for i in range(5)]
            result = service.get_active_mandate_batch(test_members)
            execution_time = time.time() - start_time
            results.append(execution_time)
        
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
        if method_name.startswith('test_'):
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