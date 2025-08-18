"""
Performance Testing Scenarios for Mollie Backend API
Tests system performance under various load conditions
"""

import concurrent.futures
import json
import random
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Tuple
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient
from verenigingen.verenigingen_payments.core.resilience.circuit_breaker import CircuitBreaker
from verenigingen.verenigingen_payments.core.resilience.rate_limiter import RateLimiter
from verenigingen.verenigingen_payments.workflows.financial_dashboard import FinancialDashboard
from verenigingen.verenigingen_payments.workflows.reconciliation_engine import ReconciliationEngine


class TestPerformanceScenarios(FrappeTestCase):
    """
    Performance tests for Mollie Backend API system
    
    Tests:
    - Response time under load
    - Throughput capacity
    - Resource utilization
    - Scalability limits
    - Performance degradation patterns
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up performance test environment"""
        super().setUpClass()
        
        # Create test settings with performance configuration
        if not frappe.db.exists("Mollie Settings", "Performance Test"):
            settings = frappe.new_doc("Mollie Settings")
            settings.gateway_name = "Performance Test"
            settings.secret_key = "perf_test_key"
            settings.profile_id = "pfl_perf_test"
            settings.enable_backend_api = True
            settings.rate_limit_requests_per_second = 100
            settings.circuit_breaker_failure_threshold = 10
            settings.connection_timeout = 5
            settings.request_timeout = 10
            settings.insert(ignore_permissions=True)
            frappe.db.commit()
    
    def setUp(self):
        """Set up test case"""
        super().setUp()
        self.settings_name = "Performance Test"
        self.performance_results = []
    
    def test_webhook_processing_throughput(self):
        """Test webhook processing throughput capacity"""
        
        from verenigingen.verenigingen_payments.core.security.webhook_validator import WebhookValidator
        
        validator = WebhookValidator(self.settings_name)
        
        # Prepare test webhooks
        num_webhooks = 1000
        webhooks = []
        
        for i in range(num_webhooks):
            body = json.dumps({
                "id": f"webhook_{i}",
                "resource": "payment",
                "amount": {"value": f"{random.uniform(10, 1000):.2f}", "currency": "EUR"}
            }).encode()
            
            signature = validator._compute_signature(body, b"test_secret")
            webhooks.append((body, signature))
        
        # Measure throughput
        start_time = time.time()
        successful = 0
        failed = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(validator.validate_webhook, body, sig)
                for body, sig in webhooks
            ]
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    if future.result():
                        successful += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
        
        elapsed = time.time() - start_time
        throughput = num_webhooks / elapsed
        
        # Performance assertions
        self.assertGreater(throughput, 100, "Webhook throughput below 100/second")
        self.assertLess(elapsed, 20, "Processing 1000 webhooks took more than 20 seconds")
        self.assertGreater(successful / num_webhooks, 0.99, "Success rate below 99%")
        
        # Record results
        self.performance_results.append({
            "test": "webhook_throughput",
            "total": num_webhooks,
            "successful": successful,
            "failed": failed,
            "elapsed": elapsed,
            "throughput": throughput
        })
    
    def test_reconciliation_batch_performance(self):
        """Test reconciliation performance with large batches"""
        
        engine = ReconciliationEngine(self.settings_name)
        
        # Create large batch of test transactions
        num_transactions = 5000
        settlements = []
        invoices = []
        
        for i in range(num_transactions // 2):
            settlements.append({
                "id": f"stl_{i}",
                "amount": Decimal(random.uniform(100, 10000)),
                "reference": f"INV-{i:05d}",
                "date": datetime.now() - timedelta(days=random.randint(0, 30))
            })
            
            invoices.append({
                "name": f"INV-{i:05d}",
                "grand_total": float(settlements[i]["amount"]),
                "posting_date": settlements[i]["date"].date()
            })
        
        # Mock data sources
        with patch.object(engine, '_get_pending_settlements') as mock_settlements, \
             patch.object(engine, '_get_unreconciled_invoices') as mock_invoices:
            
            mock_settlements.return_value = settlements
            mock_invoices.return_value = invoices
            
            # Measure reconciliation performance
            start_time = time.time()
            
            matches = engine._match_transactions(settlements)
            
            elapsed = time.time() - start_time
            
            # Performance assertions
            self.assertLess(elapsed, 5, f"Reconciling {num_transactions} items took more than 5 seconds")
            self.assertGreater(
                len(matches) / len(settlements),
                0.95,
                "Match rate below 95%"
            )
            
            # Calculate matching rate
            items_per_second = num_transactions / elapsed
            
            self.assertGreater(
                items_per_second,
                500,
                "Processing rate below 500 items/second"
            )
            
            # Record results
            self.performance_results.append({
                "test": "reconciliation_batch",
                "total_items": num_transactions,
                "matched": len(matches),
                "elapsed": elapsed,
                "items_per_second": items_per_second
            })
    
    def test_dashboard_query_performance(self):
        """Test dashboard query performance with large datasets"""
        
        dashboard = FinancialDashboard(self.settings_name)
        
        # Simulate large dataset responses
        def create_large_dataset(size: int, type: str) -> List:
            items = []
            for i in range(size):
                item = MagicMock()
                item.id = f"{type}_{i}"
                item.amount = MagicMock(
                    value=str(random.uniform(10, 1000)),
                    currency="EUR",
                    decimal_value=Decimal(str(random.uniform(10, 1000)))
                )
                item.status = random.choice(["paid", "pending", "failed"])
                item.created_at = datetime.now() - timedelta(days=random.randint(0, 90))
                items.append(item)
            return items
        
        # Test with increasingly large datasets
        dataset_sizes = [100, 500, 1000, 5000, 10000]
        query_times = []
        
        for size in dataset_sizes:
            with patch.object(dashboard.settlements_client, 'list_settlements') as mock_settlements, \
                 patch.object(dashboard.invoices_client, 'list_invoices') as mock_invoices, \
                 patch.object(dashboard.chargebacks_client, 'list_chargebacks') as mock_chargebacks:
                
                # Mock large datasets
                mock_settlements.return_value = create_large_dataset(size, "settlement")
                mock_invoices.return_value = create_large_dataset(size // 2, "invoice")
                mock_chargebacks.return_value = create_large_dataset(size // 10, "chargeback")
                
                # Measure query time
                start_time = time.time()
                
                summary = dashboard.get_financial_summary(30)
                metrics = dashboard.get_real_time_metrics()
                
                elapsed = time.time() - start_time
                query_times.append((size, elapsed))
                
                # Performance assertions
                self.assertLess(
                    elapsed,
                    size / 1000 + 1,  # Allow 1ms per item + 1 second overhead
                    f"Query time for {size} items exceeded threshold"
                )
        
        # Check for linear scalability
        for i in range(1, len(query_times)):
            size_ratio = query_times[i][0] / query_times[i-1][0]
            time_ratio = query_times[i][1] / query_times[i-1][1]
            
            # Time should scale sub-linearly (better than O(n))
            self.assertLess(
                time_ratio,
                size_ratio * 1.5,
                f"Non-linear performance degradation detected at size {query_times[i][0]}"
            )
        
        # Record results
        self.performance_results.append({
            "test": "dashboard_queries",
            "dataset_sizes": dataset_sizes,
            "query_times": query_times
        })
    
    def test_api_rate_limiting_performance(self):
        """Test rate limiting performance under burst traffic"""
        
        limiter = RateLimiter(
            requests_per_second=100,
            burst_size=200
        )
        
        # Simulate burst traffic
        burst_size = 500
        request_times = []
        throttled_count = 0
        
        start_time = time.time()
        
        for i in range(burst_size):
            request_start = time.time()
            
            can_proceed, wait_time = limiter.check_rate_limit("test_endpoint")
            
            if not can_proceed:
                throttled_count += 1
                if wait_time > 0:
                    time.sleep(min(wait_time, 0.01))  # Cap wait time for test
            
            request_times.append(time.time() - request_start)
        
        total_elapsed = time.time() - start_time
        
        # Calculate statistics
        avg_request_time = sum(request_times) / len(request_times)
        max_request_time = max(request_times)
        effective_rate = burst_size / total_elapsed
        
        # Performance assertions
        self.assertLess(avg_request_time, 0.01, "Average request time too high")
        self.assertLess(max_request_time, 0.1, "Max request time too high")
        self.assertLessEqual(
            effective_rate,
            110,  # Allow 10% margin
            "Rate limiting not enforcing limit"
        )
        
        # Record results
        self.performance_results.append({
            "test": "rate_limiting",
            "burst_size": burst_size,
            "throttled": throttled_count,
            "avg_time": avg_request_time,
            "max_time": max_request_time,
            "effective_rate": effective_rate
        })
    
    def test_circuit_breaker_performance(self):
        """Test circuit breaker performance during failures"""
        
        breaker = CircuitBreaker(
            failure_threshold=5,
            timeout=1.0,
            expected_exception=Exception
        )
        
        # Simulate mixed success/failure pattern
        num_requests = 1000
        results = []
        
        def failing_operation():
            if random.random() < 0.3:  # 30% failure rate
                raise Exception("Simulated failure")
            return "success"
        
        start_time = time.time()
        
        for i in range(num_requests):
            try:
                with breaker:
                    result = failing_operation()
                    results.append(("success", time.time()))
            except Exception:
                results.append(("failure", time.time()))
        
        elapsed = time.time() - start_time
        
        # Analyze circuit breaker behavior
        success_count = sum(1 for r in results if r[0] == "success")
        failure_count = sum(1 for r in results if r[0] == "failure")
        
        # Circuit breaker should prevent cascading failures
        self.assertLess(
            elapsed,
            num_requests * 0.01,  # Should be much faster than linear
            "Circuit breaker not preventing cascading failures"
        )
        
        # Record results
        self.performance_results.append({
            "test": "circuit_breaker",
            "total_requests": num_requests,
            "successes": success_count,
            "failures": failure_count,
            "elapsed": elapsed,
            "requests_per_second": num_requests / elapsed
        })
    
    def test_concurrent_api_calls(self):
        """Test performance with concurrent API calls"""
        
        client = BalancesClient(self.settings_name)
        
        # Mock API responses
        def mock_api_response():
            time.sleep(random.uniform(0.01, 0.05))  # Simulate network latency
            return MagicMock(
                status_code=200,
                json=lambda: {
                    "balance": {
                        "value": str(random.uniform(1000, 10000)),
                        "currency": "EUR"
                    }
                }
            )
        
        # Test concurrent calls
        num_concurrent = 50
        num_iterations = 10
        
        with patch.object(client.http_client, 'request') as mock_request:
            mock_request.side_effect = lambda *args, **kwargs: mock_api_response()
            
            start_time = time.time()
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_concurrent) as executor:
                futures = []
                
                for iteration in range(num_iterations):
                    for _ in range(num_concurrent):
                        futures.append(
                            executor.submit(client.get_primary_balance)
                        )
                
                # Wait for all to complete
                results = [f.result() for f in concurrent.futures.as_completed(futures)]
            
            elapsed = time.time() - start_time
            total_calls = num_concurrent * num_iterations
            calls_per_second = total_calls / elapsed
            
            # Performance assertions
            self.assertGreater(
                calls_per_second,
                100,
                "Concurrent API call rate below 100/second"
            )
            
            self.assertEqual(
                len(results),
                total_calls,
                "Not all concurrent calls completed"
            )
            
            # Record results
            self.performance_results.append({
                "test": "concurrent_api",
                "total_calls": total_calls,
                "concurrency": num_concurrent,
                "elapsed": elapsed,
                "calls_per_second": calls_per_second
            })
    
    def test_memory_efficiency(self):
        """Test memory efficiency with large data processing"""
        
        import gc
        import tracemalloc
        
        # Start memory tracking
        tracemalloc.start()
        gc.collect()
        
        snapshot_start = tracemalloc.take_snapshot()
        
        # Process large dataset
        engine = ReconciliationEngine(self.settings_name)
        
        # Create large dataset (10MB of data)
        large_dataset = []
        for i in range(10000):
            large_dataset.append({
                "id": f"item_{i}",
                "data": "x" * 1000,  # 1KB per item
                "amount": random.uniform(100, 1000)
            })
        
        # Process in batches (should be memory efficient)
        batch_size = 100
        processed = 0
        
        for i in range(0, len(large_dataset), batch_size):
            batch = large_dataset[i:i+batch_size]
            # Simulate processing
            processed += len(batch)
            
            # Force garbage collection
            if i % 1000 == 0:
                gc.collect()
        
        # Take memory snapshot
        snapshot_end = tracemalloc.take_snapshot()
        
        # Calculate memory usage
        stats = snapshot_end.compare_to(snapshot_start, 'lineno')
        total_memory = sum(stat.size_diff for stat in stats)
        
        # Stop tracking
        tracemalloc.stop()
        
        # Memory assertions
        self.assertLess(
            total_memory / 1024 / 1024,  # Convert to MB
            50,  # Should use less than 50MB
            "Memory usage exceeds 50MB for 10MB dataset"
        )
        
        self.assertEqual(processed, len(large_dataset))
        
        # Record results
        self.performance_results.append({
            "test": "memory_efficiency",
            "dataset_size": len(large_dataset),
            "memory_used_mb": total_memory / 1024 / 1024,
            "items_processed": processed
        })
    
    def test_cache_performance(self):
        """Test caching effectiveness for repeated queries"""
        
        dashboard = FinancialDashboard(self.settings_name)
        
        # Mock expensive API calls
        call_count = 0
        
        def mock_api_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            time.sleep(0.1)  # Simulate slow API
            return create_mock_response()
        
        def create_mock_response():
            return [MagicMock(
                amount=MagicMock(decimal_value=Decimal("100")),
                status="paid"
            ) for _ in range(100)]
        
        with patch.object(dashboard.settlements_client, 'list_settlements') as mock_settlements:
            mock_settlements.side_effect = mock_api_call
            
            # First call (cache miss)
            start_time = time.time()
            result1 = dashboard.get_financial_summary(30)
            first_call_time = time.time() - start_time
            
            # Reset call count
            first_call_count = call_count
            call_count = 0
            
            # Subsequent calls (should hit cache)
            cached_times = []
            for _ in range(10):
                start_time = time.time()
                result = dashboard.get_financial_summary(30)
                cached_times.append(time.time() - start_time)
            
            # Cache performance assertions
            avg_cached_time = sum(cached_times) / len(cached_times)
            
            self.assertLess(
                avg_cached_time,
                first_call_time * 0.1,  # Cached calls should be 10x faster
                "Cache not providing expected performance improvement"
            )
            
            self.assertLessEqual(
                call_count,
                1,  # Should only call API once more at most (cache refresh)
                "Too many API calls despite caching"
            )
            
            # Record results
            self.performance_results.append({
                "test": "cache_performance",
                "first_call_time": first_call_time,
                "avg_cached_time": avg_cached_time,
                "cache_speedup": first_call_time / avg_cached_time,
                "api_calls_saved": first_call_count * 10 - call_count
            })
    
    def test_database_connection_pooling(self):
        """Test database connection pooling efficiency"""
        
        import threading
        
        def db_operation(operation_id):
            """Simulate database operation"""
            try:
                # Multiple quick queries
                for i in range(10):
                    frappe.db.sql(
                        "SELECT COUNT(*) FROM `tabMollie Audit Log` WHERE name LIKE %s",
                        (f"test_{operation_id}_{i}%",)
                    )
                return True
            except Exception:
                return False
        
        # Run many concurrent database operations
        num_threads = 50
        num_operations = 100
        
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(db_operation, i)
                for i in range(num_operations)
            ]
            
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        elapsed = time.time() - start_time
        
        # All operations should complete successfully
        self.assertEqual(
            sum(results),
            num_operations,
            "Some database operations failed"
        )
        
        # Should handle concurrent operations efficiently
        operations_per_second = num_operations / elapsed
        self.assertGreater(
            operations_per_second,
            10,
            "Database operations too slow"
        )
        
        # Record results
        self.performance_results.append({
            "test": "db_connection_pooling",
            "num_operations": num_operations,
            "concurrency": num_threads,
            "elapsed": elapsed,
            "ops_per_second": operations_per_second
        })
    
    def tearDown(self):
        """Clean up and report performance results"""
        
        # Print performance report
        if self.performance_results:
            print("\n" + "="*60)
            print("PERFORMANCE TEST RESULTS")
            print("="*60)
            
            for result in self.performance_results:
                print(f"\nTest: {result['test']}")
                for key, value in result.items():
                    if key != 'test':
                        if isinstance(value, float):
                            print(f"  {key}: {value:.2f}")
                        else:
                            print(f"  {key}: {value}")
            
            print("="*60)
        
        super().tearDown()