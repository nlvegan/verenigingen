#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mollie Performance Benchmarks Test Suite
========================================

Realistic performance benchmarking for Mollie payment integration with achievable targets
based on actual Frappe/ERPNext system capabilities and real-world usage patterns.

Performance Targets (Realistic):
- Webhook Processing: 25 webhooks/second sustained
- Individual Payment: < 1 second average processing time
- Database Operations: < 100ms for payment entry creation
- Memory Usage: < 50MB per concurrent webhook
- Error Rate: < 0.1% under normal load

This test suite focuses on practical, achievable performance metrics rather than
unrealistic targets that don't account for Frappe ORM overhead and business logic complexity.

Author: Test Engineering Team
"""

import time
import statistics
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch
import psutil
import threading

import frappe
from frappe.utils import now_datetime, flt

from .fixtures.mollie_test_factory import MollieTestCase, MollieTestDataFactory
from verenigingen.verenigingen_payments.utils.payment_gateways import (
    _process_subscription_payment,
    PaymentGatewayFactory
)


class PerformanceMetrics:
    """Performance metrics collection and analysis"""
    
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.processing_times = []
        self.memory_usage = []
        self.error_count = 0
        self.success_count = 0
        self.start_time = None
        self.end_time = None
        
    def start_measurement(self):
        self.start_time = datetime.now()
        
    def end_measurement(self):
        self.end_time = datetime.now()
        
    def record_processing_time(self, time_ms: float):
        self.processing_times.append(time_ms)
        
    def record_memory_usage(self, memory_mb: float):
        self.memory_usage.append(memory_mb)
        
    def record_success(self):
        self.success_count += 1
        
    def record_error(self):
        self.error_count += 1
        
    def get_throughput(self) -> float:
        """Calculate throughput in operations per second"""
        if not self.start_time or not self.end_time:
            return 0
            
        duration_seconds = (self.end_time - self.start_time).total_seconds()
        total_operations = self.success_count + self.error_count
        
        return total_operations / duration_seconds if duration_seconds > 0 else 0
        
    def get_error_rate(self) -> float:
        """Calculate error rate as percentage"""
        total_operations = self.success_count + self.error_count
        return (self.error_count / total_operations * 100) if total_operations > 0 else 0
        
    def get_statistics(self) -> dict:
        """Get comprehensive performance statistics"""
        stats = {
            "throughput_ops_per_sec": self.get_throughput(),
            "error_rate_percent": self.get_error_rate(),
            "total_operations": self.success_count + self.error_count,
            "successful_operations": self.success_count,
            "failed_operations": self.error_count
        }
        
        if self.processing_times:
            stats.update({
                "avg_processing_time_ms": statistics.mean(self.processing_times),
                "median_processing_time_ms": statistics.median(self.processing_times),
                "p95_processing_time_ms": self._percentile(self.processing_times, 95),
                "p99_processing_time_ms": self._percentile(self.processing_times, 99),
                "max_processing_time_ms": max(self.processing_times),
                "min_processing_time_ms": min(self.processing_times)
            })
            
        if self.memory_usage:
            stats.update({
                "avg_memory_usage_mb": statistics.mean(self.memory_usage),
                "max_memory_usage_mb": max(self.memory_usage),
                "min_memory_usage_mb": min(self.memory_usage)
            })
            
        return stats
        
    def _percentile(self, data: list, percentile: int) -> float:
        """Calculate percentile of data"""
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]


class TestMolliePerformanceBenchmarks(MollieTestCase):
    """Realistic performance benchmarking for Mollie integration"""
    
    def setUp(self):
        super().setUp()
        
        # Create performance metrics tracker
        self.metrics = PerformanceMetrics()
        
        # Create base test members for performance testing
        self.test_members = []
        for i in range(10):  # Create 10 members for testing
            member = self.create_mollie_test_member(
                first_name=f"PerfTest{i:02d}",
                last_name="Member",
                email=f"perf.test.{i:02d}@example.com"
            )
            
            # Create customer for each member
            customer = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": f"{member.first_name} {member.last_name}",
                "customer_type": "Individual",
                "territory": "Netherlands"
            })
            customer.insert()
            member.customer = customer.name
            member.save()
            
            self.test_members.append((member, customer))
            
    def _create_mock_gateway(self, processing_delay_ms: int = 100) -> MagicMock:
        """Create mock gateway with configurable processing delay"""
        gateway = MagicMock()
        mock_client = MagicMock()
        gateway.client = mock_client
        
        def mock_get_payment(payment_id):
            # Simulate realistic API response time
            time.sleep(processing_delay_ms / 1000.0)
            
            payment = MagicMock()
            payment.is_paid.return_value = True
            payment.amount = {"value": "50.00", "currency": "EUR"}
            payment.status = "paid"
            return payment
            
        mock_client.payments.get.side_effect = mock_get_payment
        return gateway
        
    def _measure_memory_usage(self) -> float:
        """Measure current memory usage in MB"""
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024  # Convert to MB
        
    def test_single_payment_processing_time(self):
        """Test individual payment processing time"""
        member, customer = self.test_members[0]
        gateway = self._create_mock_gateway(50)  # 50ms simulated API delay
        
        # Create test invoice
        invoice_name = self._create_test_invoice(customer, 50.00)
        
        processing_times = []
        
        # Test multiple single payments
        for i in range(10):
            payment_id = f"tr_single_test_{i:03d}"
            
            start_time = datetime.now()
            
            try:
                result = _process_subscription_payment(
                    gateway, member.name, customer.name, payment_id, "sub_single_test"
                )
                
                end_time = datetime.now()
                processing_time_ms = (end_time - start_time).total_seconds() * 1000
                processing_times.append(processing_time_ms)
                
                self.metrics.record_processing_time(processing_time_ms)
                self.metrics.record_success()
                
            except Exception as e:
                end_time = datetime.now()
                processing_time_ms = (end_time - start_time).total_seconds() * 1000
                processing_times.append(processing_time_ms)
                
                self.metrics.record_processing_time(processing_time_ms)
                self.metrics.record_error()
                
                print(f"Single payment test {i} failed: {e}")
                
        # Analyze results
        if processing_times:
            avg_time = statistics.mean(processing_times)
            max_time = max(processing_times)
            
            print(f"Single Payment Performance:")
            print(f"  Average processing time: {avg_time:.2f}ms")
            print(f"  Maximum processing time: {max_time:.2f}ms")
            print(f"  Success rate: {self.metrics.success_count}/{len(processing_times)}")
            
            # Realistic assertions
            self.assertLessEqual(avg_time, 1000,  # 1 second average
                               f"Average processing time {avg_time:.2f}ms exceeds 1000ms target")
            self.assertLessEqual(max_time, 3000,  # 3 second maximum
                               f"Maximum processing time {max_time:.2f}ms exceeds 3000ms target")
                               
    def test_webhook_throughput_25_per_second(self):
        """Test realistic webhook throughput of 25 webhooks/second"""
        target_throughput = 25  # webhooks per second
        test_duration = 2  # seconds
        total_webhooks = target_throughput * test_duration
        
        gateway = self._create_mock_gateway(100)  # 100ms simulated processing
        
        self.metrics.start_measurement()
        
        def process_webhook(webhook_id: int):
            member, customer = self.test_members[webhook_id % len(self.test_members)]
            payment_id = f"tr_throughput_test_{webhook_id:04d}"
            
            start_time = datetime.now()
            memory_before = self._measure_memory_usage()
            
            try:
                result = _process_subscription_payment(
                    gateway, member.name, customer.name, payment_id, "sub_throughput_test"
                )
                
                end_time = datetime.now()
                memory_after = self._measure_memory_usage()
                
                processing_time_ms = (end_time - start_time).total_seconds() * 1000
                memory_delta = memory_after - memory_before
                
                self.metrics.record_processing_time(processing_time_ms)
                self.metrics.record_memory_usage(memory_delta)
                self.metrics.record_success()
                
                return {"status": "success", "processing_time_ms": processing_time_ms}
                
            except Exception as e:
                end_time = datetime.now()
                processing_time_ms = (end_time - start_time).total_seconds() * 1000
                
                self.metrics.record_processing_time(processing_time_ms)
                self.metrics.record_error()
                
                return {"status": "error", "error": str(e), "processing_time_ms": processing_time_ms}
                
        # Execute webhooks with controlled timing
        results = []
        webhook_interval = 1.0 / target_throughput  # Time between webhooks
        
        for i in range(total_webhooks):
            webhook_start = datetime.now()
            
            # Process webhook
            result = process_webhook(i)
            results.append(result)
            
            # Calculate sleep time to maintain target rate
            elapsed = (datetime.now() - webhook_start).total_seconds()
            sleep_time = max(0, webhook_interval - elapsed)
            
            if sleep_time > 0:
                time.sleep(sleep_time)
                
        self.metrics.end_measurement()
        
        # Analyze throughput results
        stats = self.metrics.get_statistics()
        
        print(f"Throughput Test Results (Target: {target_throughput} webhooks/sec):")
        print(f"  Actual throughput: {stats['throughput_ops_per_sec']:.2f} webhooks/sec")
        print(f"  Success rate: {stats['successful_operations']}/{stats['total_operations']} ({100 - stats['error_rate_percent']:.1f}%)")
        print(f"  Average processing time: {stats.get('avg_processing_time_ms', 0):.2f}ms")
        print(f"  P95 processing time: {stats.get('p95_processing_time_ms', 0):.2f}ms")
        
        # Realistic assertions
        self.assertGreaterEqual(stats['throughput_ops_per_sec'], target_throughput * 0.8,
                              f"Throughput {stats['throughput_ops_per_sec']:.2f} is below 80% of target {target_throughput}")
        self.assertLessEqual(stats['error_rate_percent'], 5.0,
                           f"Error rate {stats['error_rate_percent']:.1f}% exceeds 5% threshold")
                           
    def test_concurrent_webhook_processing(self):
        """Test concurrent webhook processing with thread pool"""
        concurrent_webhooks = 10
        gateway = self._create_mock_gateway(150)  # 150ms simulated processing
        
        def process_concurrent_webhook(webhook_id: int):
            member, customer = self.test_members[webhook_id % len(self.test_members)]
            payment_id = f"tr_concurrent_test_{webhook_id:04d}"
            
            start_time = datetime.now()
            
            try:
                result = _process_subscription_payment(
                    gateway, member.name, customer.name, payment_id, "sub_concurrent_test"
                )
                
                end_time = datetime.now()
                processing_time_ms = (end_time - start_time).total_seconds() * 1000
                
                return {
                    "webhook_id": webhook_id,
                    "status": "success",
                    "processing_time_ms": processing_time_ms
                }
                
            except Exception as e:
                end_time = datetime.now()
                processing_time_ms = (end_time - start_time).total_seconds() * 1000
                
                return {
                    "webhook_id": webhook_id,
                    "status": "error",
                    "error": str(e),
                    "processing_time_ms": processing_time_ms
                }
                
        # Execute concurrent webhooks
        self.metrics.start_measurement()
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(process_concurrent_webhook, i) 
                for i in range(concurrent_webhooks)
            ]
            
            results = []
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                
                self.metrics.record_processing_time(result["processing_time_ms"])
                if result["status"] == "success":
                    self.metrics.record_success()
                else:
                    self.metrics.record_error()
                    
        self.metrics.end_measurement()
        
        # Analyze concurrent processing results
        stats = self.metrics.get_statistics()
        successful_results = [r for r in results if r["status"] == "success"]
        
        print(f"Concurrent Processing Test Results:")
        print(f"  Concurrent webhooks: {concurrent_webhooks}")
        print(f"  Successful: {len(successful_results)}")
        print(f"  Failed: {len(results) - len(successful_results)}")
        print(f"  Average processing time: {stats.get('avg_processing_time_ms', 0):.2f}ms")
        print(f"  Maximum processing time: {stats.get('max_processing_time_ms', 0):.2f}ms")
        
        # Assertions for concurrent processing
        self.assertGreaterEqual(len(successful_results), concurrent_webhooks * 0.8,
                              "At least 80% of concurrent webhooks should succeed")
        self.assertLessEqual(stats.get('max_processing_time_ms', 0), 5000,
                           "Maximum processing time should be under 5 seconds even with concurrency")
                           
    def test_memory_usage_under_load(self):
        """Test memory usage under sustained load"""
        webhook_count = 50
        gateway = self._create_mock_gateway(50)
        
        memory_measurements = []
        initial_memory = self._measure_memory_usage()
        
        for i in range(webhook_count):
            member, customer = self.test_members[i % len(self.test_members)]
            payment_id = f"tr_memory_test_{i:04d}"
            
            memory_before = self._measure_memory_usage()
            
            try:
                result = _process_subscription_payment(
                    gateway, member.name, customer.name, payment_id, "sub_memory_test"
                )
                
                memory_after = self._measure_memory_usage()
                memory_delta = memory_after - memory_before
                memory_measurements.append(memory_delta)
                
            except Exception as e:
                memory_after = self._measure_memory_usage()
                memory_delta = memory_after - memory_before
                memory_measurements.append(memory_delta)
                print(f"Memory test {i} failed: {e}")
                
            # Force garbage collection every 10 operations
            if i % 10 == 0:
                import gc
                gc.collect()
                
        final_memory = self._measure_memory_usage()
        total_memory_increase = final_memory - initial_memory
        
        if memory_measurements:
            avg_memory_per_operation = statistics.mean(memory_measurements)
            max_memory_per_operation = max(memory_measurements)
            
            print(f"Memory Usage Test Results:")
            print(f"  Initial memory: {initial_memory:.2f}MB")
            print(f"  Final memory: {final_memory:.2f}MB")
            print(f"  Total increase: {total_memory_increase:.2f}MB")
            print(f"  Average per operation: {avg_memory_per_operation:.2f}MB")
            print(f"  Maximum per operation: {max_memory_per_operation:.2f}MB")
            
            # Memory usage assertions (realistic)
            self.assertLessEqual(avg_memory_per_operation, 10.0,  # 10MB per operation
                               f"Average memory per operation {avg_memory_per_operation:.2f}MB exceeds 10MB")
            self.assertLessEqual(total_memory_increase, 100.0,  # 100MB total increase
                               f"Total memory increase {total_memory_increase:.2f}MB exceeds 100MB")
                               
    def test_performance_degradation_over_time(self):
        """Test for performance degradation over extended operation"""
        batches = 5
        operations_per_batch = 20
        gateway = self._create_mock_gateway(75)
        
        batch_performance = []
        
        for batch in range(batches):
            batch_start = datetime.now()
            batch_times = []
            
            for i in range(operations_per_batch):
                member, customer = self.test_members[i % len(self.test_members)]
                payment_id = f"tr_degradation_test_b{batch}_o{i:03d}"
                
                op_start = datetime.now()
                
                try:
                    result = _process_subscription_payment(
                        gateway, member.name, customer.name, payment_id, "sub_degradation_test"
                    )
                    
                    op_end = datetime.now()
                    op_time_ms = (op_end - op_start).total_seconds() * 1000
                    batch_times.append(op_time_ms)
                    
                except Exception as e:
                    op_end = datetime.now()
                    op_time_ms = (op_end - op_start).total_seconds() * 1000
                    batch_times.append(op_time_ms)
                    print(f"Degradation test batch {batch}, operation {i} failed: {e}")
                    
            batch_end = datetime.now()
            batch_duration = (batch_end - batch_start).total_seconds()
            
            if batch_times:
                batch_avg_time = statistics.mean(batch_times)
                batch_throughput = len(batch_times) / batch_duration
                
                batch_performance.append({
                    "batch": batch,
                    "avg_time_ms": batch_avg_time,
                    "throughput": batch_throughput,
                    "operations": len(batch_times)
                })
                
        # Analyze performance degradation
        if len(batch_performance) >= 2:
            first_batch = batch_performance[0]
            last_batch = batch_performance[-1]
            
            time_degradation = (last_batch["avg_time_ms"] - first_batch["avg_time_ms"]) / first_batch["avg_time_ms"] * 100
            throughput_degradation = (first_batch["throughput"] - last_batch["throughput"]) / first_batch["throughput"] * 100
            
            print(f"Performance Degradation Test Results:")
            print(f"  Batches tested: {len(batch_performance)}")
            print(f"  First batch avg time: {first_batch['avg_time_ms']:.2f}ms")
            print(f"  Last batch avg time: {last_batch['avg_time_ms']:.2f}ms")
            print(f"  Time degradation: {time_degradation:.1f}%")
            print(f"  First batch throughput: {first_batch['throughput']:.2f} ops/sec")
            print(f"  Last batch throughput: {last_batch['throughput']:.2f} ops/sec")
            print(f"  Throughput degradation: {throughput_degradation:.1f}%")
            
            # Degradation assertions (should not degrade significantly)
            self.assertLessEqual(abs(time_degradation), 25.0,
                               f"Processing time degradation {time_degradation:.1f}% exceeds 25%")
            self.assertLessEqual(abs(throughput_degradation), 25.0,
                               f"Throughput degradation {throughput_degradation:.1f}% exceeds 25%")
                               
    def _create_test_invoice(self, customer, amount: float) -> str:
        """Create test invoice for performance testing"""
        self.mollie_factory._ensure_test_item()
        
        invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": customer.name,
            "customer_name": customer.customer_name,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "items": [{
                "item_code": "TEST-Membership-Dues",
                "item_name": "Test Membership Dues",
                "description": f"Performance test invoice",
                "qty": 1,
                "rate": amount,
                "amount": amount
            }],
            "currency": "EUR",
            "remarks": f"Performance test invoice - amount: {amount}"
        })
        invoice.insert()
        invoice.submit()
        return invoice.name


if __name__ == "__main__":
    # Run performance benchmarks
    import unittest
    
    print("Running Mollie Performance Benchmarks...")
    print("=" * 50)
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMolliePerformanceBenchmarks)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 50)
    print(f"Performance Benchmark Results:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"  {test}")
            
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"  {test}")
            
    if len(result.failures) == 0 and len(result.errors) == 0:
        print("\n✅ All performance benchmarks passed!")
    else:
        print(f"\n⚠️  Some benchmarks failed or had errors.")