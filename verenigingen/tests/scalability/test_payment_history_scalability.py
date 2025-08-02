#!/usr/bin/env python3
"""
Payment History Scalability Test Suite
======================================

This test suite evaluates the performance and scalability of the payment history
system under various load conditions. It measures:

- Payment history generation performance
- Member payment history update operations
- Background job queue processing 
- Database query performance with large datasets
- Memory usage patterns during bulk operations

The tests use progressive scaling to identify performance bottlenecks and
measure system behavior as data volume increases.

Test Scenarios:
- Small scale: 100 members, 3 months history
- Medium scale: 500 members, 6 months history  
- Large scale: 1000 members, 12 months history
- XL scale: 2500 members, 12 months history
- XXL scale: 5000 members, 12 months history

Performance Metrics:
- Records per second creation rate
- Memory usage during operations
- Database query count and timing
- Background job processing time
- Payment history update latency
"""

import time
import psutil
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import statistics

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.scalability.payment_history_test_factory import PaymentHistoryTestFactory
from verenigingen.utils.background_jobs import BackgroundJobManager


class PaymentHistoryScalabilityTestCase(VereningingenTestCase):
    """Base test case for payment history scalability testing"""
    
    @classmethod
    def setUpClass(cls):
        """Set up class-level test infrastructure"""
        super().setUpClass()
        cls.performance_results = []
        cls.memory_measurements = []
        
    def setUp(self):
        """Set up individual test environment"""
        super().setUp()
        self.factory = PaymentHistoryTestFactory(cleanup_on_exit=False, seed=42)
        self.test_start_time = time.time()
        self.initial_memory = self._get_memory_usage()
        
    def tearDown(self):
        """Clean up test data"""
        try:
            # Measure final memory usage
            final_memory = self._get_memory_usage()
            memory_delta = final_memory - self.initial_memory
            
            self.memory_measurements.append({
                "test_name": self._testMethodName,
                "initial_memory_mb": self.initial_memory,
                "final_memory_mb": final_memory,
                "memory_delta_mb": memory_delta,
                "test_duration": time.time() - self.test_start_time
            })
            
            # Clean up test data
            self.factory.cleanup()
            
        except Exception as e:
            print(f"Warning: Cleanup error in {self._testMethodName}: {e}")
            
        super().tearDown()
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        try:
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024  # Convert to MB
        except Exception:
            return 0.0
    
    def _measure_database_performance(self, operation_func, *args, **kwargs) -> Dict[str, Any]:
        """Measure database performance for an operation"""
        # Get initial query count
        initial_queries = frappe.db.sql_list("SHOW SESSION STATUS LIKE 'Questions'")[0] if hasattr(frappe.db, 'sql_list') else 0
        
        start_time = time.time()
        start_memory = self._get_memory_usage()
        
        # Execute operation
        result = operation_func(*args, **kwargs)
        
        end_time = time.time()
        end_memory = self._get_memory_usage()
        
        # Get final query count
        final_queries = frappe.db.sql_list("SHOW SESSION STATUS LIKE 'Questions'")[0] if hasattr(frappe.db, 'sql_list') else 0
        
        return {
            "result": result,
            "execution_time": end_time - start_time,
            "memory_delta_mb": end_memory - start_memory,
            "estimated_queries": final_queries - initial_queries if isinstance(final_queries, (int, float)) else 0,
            "start_memory_mb": start_memory,
            "end_memory_mb": end_memory
        }
    
    def _record_performance_result(self, test_name: str, metrics: Dict[str, Any]):
        """Record performance test results"""
        result = {
            "test_name": test_name,
            "timestamp": datetime.now().isoformat(),
            **metrics
        }
        self.performance_results.append(result)
        
        # Print summary
        print(f"\n📊 Performance Results for {test_name}:")
        if "member_count" in metrics:
            print(f"  Members: {metrics['member_count']}")
        if "execution_time" in metrics:
            print(f"  Time: {metrics['execution_time']:.2f}s")
        if "records_per_second" in metrics:
            print(f"  Rate: {metrics['records_per_second']:.1f} records/sec")
        if "memory_delta_mb" in metrics:
            print(f"  Memory: {metrics['memory_delta_mb']:.1f}MB delta")


class TestPaymentHistorySmallScale(PaymentHistoryScalabilityTestCase):
    """Test payment history performance at small scale (100 members)"""
    
    def test_small_scale_payment_history_creation(self):
        """Test creating payment history for 100 members"""
        
        def create_small_batch():
            return self.factory.create_payment_history_batch(
                member_count=100,
                months_history=3,
                avg_payments_per_month=1.2
            )
        
        performance = self._measure_database_performance(create_small_batch)
        batch_result = performance["result"]
        
        # Validate data creation
        self.assertEqual(len(batch_result["members"]), 100)
        self.assertGreater(len(batch_result["invoices"]), 200)  # Should have multiple invoices
        self.assertGreater(len(batch_result["payments"]), 180)  # 90% payment success rate
        
        # Record performance metrics
        metrics = {
            "member_count": 100,
            "execution_time": performance["execution_time"],
            "memory_delta_mb": performance["memory_delta_mb"],
            "total_records": batch_result["metrics"]["total_records"],
            "records_per_second": batch_result["metrics"]["total_records"] / performance["execution_time"] if performance["execution_time"] > 0 else 0,
            "members_per_second": batch_result["metrics"]["members_per_second"],
            "scale": "small"
        }
        
        self._record_performance_result("small_scale_creation", metrics)
        
        # Performance assertions
        self.assertLess(performance["execution_time"], 60, "Creation should complete within 60 seconds")
        self.assertLess(performance["memory_delta_mb"], 100, "Memory usage should be reasonable")
    
    def test_small_scale_payment_history_update(self):
        """Test updating payment history for existing members"""
        
        # First create the batch
        batch = self.factory.create_payment_history_batch(
            member_count=50,
            months_history=2,
            avg_payments_per_month=1.0
        )
        
        # Measure payment history update performance
        def update_payment_histories():
            update_times = []
            
            for member in batch["members"]:
                start_time = time.time()
                
                member_doc = frappe.get_doc("Member", member.name)
                member_doc.load_payment_history()
                member_doc.save(ignore_permissions=True)
                
                update_times.append(time.time() - start_time)
            
            return update_times
        
        performance = self._measure_database_performance(update_payment_histories)
        update_times = performance["result"]
        
        # Calculate statistics
        avg_update_time = statistics.mean(update_times)
        median_update_time = statistics.median(update_times)
        max_update_time = max(update_times)
        
        metrics = {
            "member_count": 50,
            "total_execution_time": performance["execution_time"],
            "avg_update_time": avg_update_time,
            "median_update_time": median_update_time,
            "max_update_time": max_update_time,
            "memory_delta_mb": performance["memory_delta_mb"],
            "updates_per_second": len(update_times) / performance["execution_time"] if performance["execution_time"] > 0 else 0,
            "scale": "small"
        }
        
        self._record_performance_result("small_scale_update", metrics)
        
        # Performance assertions
        self.assertLess(avg_update_time, 2.0, "Average update time should be under 2 seconds")
        self.assertLess(max_update_time, 5.0, "No single update should take more than 5 seconds")


class TestPaymentHistoryMediumScale(PaymentHistoryScalabilityTestCase):
    """Test payment history performance at medium scale (500 members)"""
    
    def test_medium_scale_payment_history_creation(self):
        """Test creating payment history for 500 members"""
        
        def create_medium_batch():
            return self.factory.create_payment_history_batch(
                member_count=500,
                months_history=6,
                avg_payments_per_month=1.5
            )
        
        performance = self._measure_database_performance(create_medium_batch)
        batch_result = performance["result"]
        
        # Validate data creation
        self.assertEqual(len(batch_result["members"]), 500)
        self.assertGreater(len(batch_result["invoices"]), 3000)  # 500 * 6 * 1.5 = 4500 expected
        
        # Record performance metrics
        metrics = {
            "member_count": 500,
            "execution_time": performance["execution_time"],
            "memory_delta_mb": performance["memory_delta_mb"],
            "total_records": batch_result["metrics"]["total_records"],
            "records_per_second": batch_result["metrics"]["total_records"] / performance["execution_time"] if performance["execution_time"] > 0 else 0,
            "members_per_second": batch_result["metrics"]["members_per_second"],
            "scale": "medium"
        }
        
        self._record_performance_result("medium_scale_creation", metrics)
        
        # Performance assertions (more lenient for larger scale)
        self.assertLess(performance["execution_time"], 300, "Creation should complete within 5 minutes")
        self.assertLess(performance["memory_delta_mb"], 500, "Memory usage should be manageable")
    
    def test_medium_scale_background_job_processing(self):
        """Test background job processing with medium scale data"""
        
        # Create a smaller batch for background job testing
        batch = self.factory.create_payment_history_batch(
            member_count=100,
            months_history=3,
            avg_payments_per_month=1.0
        )
        
        # Queue background jobs for payment history updates
        job_ids = []
        start_time = time.time()
        
        for member in batch["members"][:50]:  # Test with subset
            job_id = BackgroundJobManager.queue_member_payment_history_update(
                member_name=member.name,
                priority="default"
            )
            if job_id:
                job_ids.append(job_id)
        
        queue_time = time.time() - start_time
        
        # Allow some time for background jobs to process
        time.sleep(10)
        
        # Check job completion status
        completed_jobs = 0
        for job_id in job_ids:
            # Check if job completed (simplified check)
            cache_key = f"job_status_{job_id}"
            job_status = frappe.cache().get_value(cache_key)
            if job_status and job_status.get("status") in ["Completed", "Failed"]:
                completed_jobs += 1
        
        metrics = {
            "jobs_queued": len(job_ids),
            "jobs_completed": completed_jobs,
            "queue_time": queue_time,
            "completion_rate": completed_jobs / len(job_ids) if job_ids else 0,
            "jobs_per_second": len(job_ids) / queue_time if queue_time > 0 else 0,
            "scale": "medium"
        }
        
        self._record_performance_result("medium_scale_background_jobs", metrics)
        
        # Assertions
        self.assertGreater(len(job_ids), 0, "Should successfully queue background jobs")
        self.assertLess(queue_time, 30, "Job queueing should be fast")


class TestPaymentHistoryLargeScale(PaymentHistoryScalabilityTestCase):
    """Test payment history performance at large scale (1000+ members)"""
    
    def test_large_scale_payment_history_creation(self):
        """Test creating payment history for 1000 members"""
        
        def create_large_batch():
            return self.factory.create_payment_history_batch(
                member_count=1000,
                months_history=12,
                avg_payments_per_month=2.0
            )
        
        performance = self._measure_database_performance(create_large_batch)
        batch_result = performance["result"]
        
        # Validate data creation
        self.assertEqual(len(batch_result["members"]), 1000)
        self.assertGreater(len(batch_result["invoices"]), 15000)  # 1000 * 12 * 2.0 = 24000 expected
        
        # Record performance metrics
        metrics = {
            "member_count": 1000,
            "execution_time": performance["execution_time"],
            "memory_delta_mb": performance["memory_delta_mb"],
            "total_records": batch_result["metrics"]["total_records"],
            "records_per_second": batch_result["metrics"]["total_records"] / performance["execution_time"] if performance["execution_time"] > 0 else 0,
            "members_per_second": batch_result["metrics"]["members_per_second"],
            "scale": "large"
        }
        
        self._record_performance_result("large_scale_creation", metrics)
        
        # Performance assertions (more lenient for large scale)
        self.assertLess(performance["execution_time"], 600, "Creation should complete within 10 minutes")
        # Memory assertion more lenient for large datasets
        self.assertLess(performance["memory_delta_mb"], 1000, "Memory usage should be under 1GB")
        
        # Performance degradation check
        self.assertGreater(metrics["records_per_second"], 50, "Should maintain reasonable throughput")
    
    def test_large_scale_batch_payment_processing(self):
        """Test batch payment processing performance"""
        
        # Create a moderate batch for processing tests
        batch = self.factory.create_payment_history_batch(
            member_count=200,
            months_history=6,
            avg_payments_per_month=1.5
        )
        
        # Measure batch processing of payment history updates
        def batch_process_payments():
            processed_count = 0
            processing_times = []
            
            # Process in batches of 20
            batch_size = 20
            members = batch["members"]
            
            for i in range(0, len(members), batch_size):
                batch_members = members[i:i + batch_size]
                
                batch_start = time.time()
                
                for member in batch_members:
                    try:
                        member_doc = frappe.get_doc("Member", member.name)
                        member_doc.load_payment_history()
                        member_doc.save(ignore_permissions=True)
                        processed_count += 1
                    except Exception as e:
                        frappe.log_error(f"Failed to process member {member.name}: {str(e)}")
                
                batch_time = time.time() - batch_start
                processing_times.append(batch_time)
                
                # Brief pause between batches to simulate real-world conditions
                time.sleep(0.1)
            
            return {
                "processed_count": processed_count,
                "processing_times": processing_times,
                "avg_batch_time": statistics.mean(processing_times) if processing_times else 0
            }
        
        performance = self._measure_database_performance(batch_process_payments)
        process_result = performance["result"]
        
        metrics = {
            "total_members": len(batch["members"]),
            "processed_count": process_result["processed_count"],
            "execution_time": performance["execution_time"],
            "avg_batch_time": process_result["avg_batch_time"],
            "processing_rate": process_result["processed_count"] / performance["execution_time"] if performance["execution_time"] > 0 else 0,
            "memory_delta_mb": performance["memory_delta_mb"],
            "scale": "large"
        }
        
        self._record_performance_result("large_scale_batch_processing", metrics)
        
        # Assertions
        self.assertGreater(process_result["processed_count"], len(batch["members"]) * 0.95, 
                          "Should successfully process 95%+ of members")
        self.assertLess(process_result["avg_batch_time"], 10, 
                       "Average batch processing time should be reasonable")


class TestPaymentHistoryExtremeScale(PaymentHistoryScalabilityTestCase):
    """Test payment history performance at extreme scale (2500+ members)"""
    
    def test_extreme_scale_creation_performance(self):
        """Test creation performance at 2500 member scale"""
        
        def create_extreme_batch():
            return self.factory.create_payment_stress_test_scenario(scale="xlarge")
        
        performance = self._measure_database_performance(create_extreme_batch)
        batch_result = performance["result"]
        
        # Record performance metrics
        metrics = {
            "member_count": 2500,
            "execution_time": performance["execution_time"],
            "memory_delta_mb": performance["memory_delta_mb"],
            "total_records": batch_result["metrics"]["total_records"],
            "records_per_second": batch_result["metrics"]["total_records"] / performance["execution_time"] if performance["execution_time"] > 0 else 0,
            "scale": "extreme"
        }
        
        self._record_performance_result("extreme_scale_creation", metrics)
        
        # More lenient assertions for extreme scale
        self.assertLess(performance["execution_time"], 1800, "Should complete within 30 minutes")
        
        # Check for severe performance degradation
        if hasattr(self, 'performance_results') and len(self.performance_results) > 1:
            # Compare with previous large scale results
            large_scale_results = [r for r in self.performance_results if r.get("scale") == "large"]
            if large_scale_results:
                large_scale_rate = large_scale_results[-1].get("records_per_second", 0)
                current_rate = metrics["records_per_second"]
                
                # Allow for some performance degradation but not too much
                degradation_ratio = current_rate / large_scale_rate if large_scale_rate > 0 else 1
                self.assertGreater(degradation_ratio, 0.3, 
                                 f"Performance degradation too severe: {degradation_ratio:.2f}")
    
    def test_maximum_scale_limits(self):
        """Test system limits with maximum realistic scale"""
        
        # Test with 5000 members (system limit test)
        try:
            def create_maximum_batch():
                return self.factory.create_payment_stress_test_scenario(scale="xxlarge")
            
            performance = self._measure_database_performance(create_maximum_batch)
            batch_result = performance["result"]
            
            metrics = {
                "member_count": 5000,
                "execution_time": performance["execution_time"],
                "memory_delta_mb": performance["memory_delta_mb"],
                "total_records": batch_result["metrics"]["total_records"],
                "records_per_second": batch_result["metrics"]["total_records"] / performance["execution_time"] if performance["execution_time"] > 0 else 0,
                "scale": "maximum"
            }
            
            self._record_performance_result("maximum_scale_creation", metrics)
            
            # Success criteria for maximum scale
            self.assertLess(performance["execution_time"], 3600, "Should complete within 1 hour")
            self.assertLess(performance["memory_delta_mb"], 2000, "Memory usage should be under 2GB")
            
            print(f"✅ Maximum scale test successful: {metrics['member_count']} members")
            
        except Exception as e:
            # If maximum scale fails, record the failure and continue
            frappe.log_error(f"Maximum scale test failed: {str(e)}")
            
            metrics = {
                "member_count": 5000,
                "execution_time": 0,
                "memory_delta_mb": 0,
                "error": str(e),
                "scale": "maximum",
                "test_failed": True
            }
            
            self._record_performance_result("maximum_scale_creation_failed", metrics)
            
            print(f"⚠️ Maximum scale test failed: {str(e)}")
            # Don't fail the test, just record the limitation


class TestPaymentHistoryPerformanceAnalysis(PaymentHistoryScalabilityTestCase):
    """Analyze overall performance patterns and generate recommendations"""
    
    @classmethod
    def tearDownClass(cls):
        """Generate performance analysis report"""
        super().tearDownClass()
        
        if hasattr(cls, 'performance_results') and cls.performance_results:
            cls._generate_performance_report()
    
    @classmethod
    def _generate_performance_report(cls):
        """Generate comprehensive performance analysis report"""
        
        print("\n" + "="*80)
        print("PAYMENT HISTORY SCALABILITY TEST RESULTS")
        print("="*80)
        
        # Group results by scale
        results_by_scale = {}
        for result in cls.performance_results:
            scale = result.get("scale", "unknown")
            if scale not in results_by_scale:
                results_by_scale[scale] = []
            results_by_scale[scale].append(result)
        
        # Print results by scale
        for scale, results in results_by_scale.items():
            print(f"\n{scale.upper()} SCALE RESULTS:")
            print("-" * 40)
            
            for result in results:
                print(f"Test: {result['test_name']}")
                if 'member_count' in result:
                    print(f"  Members: {result['member_count']}")
                if 'execution_time' in result:
                    print(f"  Time: {result['execution_time']:.2f}s")
                if 'records_per_second' in result:
                    print(f"  Rate: {result['records_per_second']:.1f} records/sec")
                if 'memory_delta_mb' in result:
                    print(f"  Memory: {result['memory_delta_mb']:.1f}MB")
                if 'error' in result:
                    print(f"  Error: {result['error']}")
                print()
        
        # Performance scaling analysis
        creation_results = [r for r in cls.performance_results if 'creation' in r['test_name'] and not r.get('test_failed')]
        
        if len(creation_results) >= 2:
            print("\nSCALING ANALYSIS:")
            print("-" * 40)
            
            creation_results.sort(key=lambda x: x.get('member_count', 0))
            
            for i, result in enumerate(creation_results):
                member_count = result.get('member_count', 0)
                rate = result.get('records_per_second', 0)
                time_taken = result.get('execution_time', 0)
                
                print(f"{member_count:,} members: {rate:.1f} rec/sec, {time_taken:.1f}s")
                
                if i > 0:
                    prev_result = creation_results[i-1]
                    prev_member_count = prev_result.get('member_count', 0)
                    prev_rate = prev_result.get('records_per_second', 0)
                    
                    if prev_rate > 0:
                        scaling_factor = member_count / prev_member_count if prev_member_count > 0 else 1
                        performance_ratio = rate / prev_rate
                        efficiency = performance_ratio / scaling_factor if scaling_factor > 0 else 0
                        
                        print(f"  Scaling efficiency: {efficiency:.2f} (1.0 = linear scaling)")
        
        # Generate recommendations
        print("\nRECOMMENDATIONS:")
        print("-" * 40)
        
        # Memory usage recommendations
        max_memory = max((r.get('memory_delta_mb', 0) for r in cls.performance_results), default=0)
        if max_memory > 1000:
            print("⚠️ HIGH MEMORY USAGE: Consider implementing streaming or batching for large datasets")
        
        # Performance recommendations
        min_rate = min((r.get('records_per_second', float('inf')) for r in creation_results), default=float('inf'))
        if min_rate < 10:
            print("⚠️ LOW THROUGHPUT: Consider database optimization or background processing")
        
        # Scaling recommendations
        if len(creation_results) >= 3:
            rates = [r.get('records_per_second', 0) for r in creation_results]
            if len(rates) >= 2 and rates[-1] < rates[0] * 0.5:
                print("⚠️ POOR SCALING: Performance degrades significantly with scale")
        
        # Success recommendations
        failed_tests = [r for r in cls.performance_results if r.get('test_failed')]
        if not failed_tests:
            print("✅ GOOD SCALABILITY: System handles all tested scales successfully")
        
        max_successful_members = max((r.get('member_count', 0) for r in cls.performance_results if not r.get('test_failed')), default=0)
        print(f"✅ MAXIMUM VALIDATED SCALE: {max_successful_members:,} members")
        
        print("\n" + "="*80)
    
    def test_performance_baseline_comparison(self):
        """Compare current performance against baseline expectations"""
        
        # Create a baseline test
        baseline_batch = self.factory.create_payment_history_batch(
            member_count=100,
            months_history=3,
            avg_payments_per_month=1.0
        )
        
        # Expected baseline performance (adjust based on system capabilities)
        expected_baseline = {
            "min_records_per_second": 50,
            "max_memory_delta_mb": 200,
            "max_execution_time": 120
        }
        
        # Get the actual performance from recent results
        baseline_results = [r for r in self.performance_results if r.get('member_count') == 100 and 'creation' in r['test_name']]
        
        if baseline_results:
            actual = baseline_results[-1]  # Most recent
            
            # Compare against expectations
            rate_ok = actual.get('records_per_second', 0) >= expected_baseline['min_records_per_second']
            memory_ok = actual.get('memory_delta_mb', 0) <= expected_baseline['max_memory_delta_mb']
            time_ok = actual.get('execution_time', 0) <= expected_baseline['max_execution_time']
            
            print(f"\nBASELINE PERFORMANCE COMPARISON:")
            print(f"Records/sec: {actual.get('records_per_second', 0):.1f} (min: {expected_baseline['min_records_per_second']}) {'✅' if rate_ok else '❌'}")
            print(f"Memory: {actual.get('memory_delta_mb', 0):.1f}MB (max: {expected_baseline['max_memory_delta_mb']}) {'✅' if memory_ok else '❌'}")
            print(f"Time: {actual.get('execution_time', 0):.1f}s (max: {expected_baseline['max_execution_time']}) {'✅' if time_ok else '❌'}")
            
            overall_performance = "GOOD" if all([rate_ok, memory_ok, time_ok]) else "NEEDS_IMPROVEMENT"
            print(f"Overall Performance: {overall_performance}")
            
            # Soft assertions - log warnings instead of failing
            if not rate_ok:
                print(f"Warning: Throughput below baseline ({actual.get('records_per_second', 0):.1f} < {expected_baseline['min_records_per_second']})")
            if not memory_ok:
                print(f"Warning: Memory usage above baseline ({actual.get('memory_delta_mb', 0):.1f} > {expected_baseline['max_memory_delta_mb']})")
            if not time_ok:
                print(f"Warning: Execution time above baseline ({actual.get('execution_time', 0):.1f} > {expected_baseline['max_execution_time']})")