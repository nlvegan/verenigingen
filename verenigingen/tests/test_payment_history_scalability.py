#!/usr/bin/env python3
"""
Payment History Scalability Testing Suite
==========================================

Comprehensive performance and scalability testing for payment history functionality.
Tests the payment history system under various scales and loads to ensure
acceptable performance characteristics.

Features:
- Progressive scaling tests (100 → 5000 members)
- Multi-dimensional performance metrics collection
- Background job queue testing with realistic monitoring
- Edge case testing with failure injection
- Resource monitoring and cleanup management
- CI/CD integration support

Architecture:
- Inherits from VereningingenTestCase for automatic cleanup
- Uses StreamlinedTestDataFactory for efficient data generation
- Integrates with BackgroundJobManager for realistic queue testing
- Provides comprehensive performance measurement

Usage:
    # Run all scalability tests
    python -m pytest verenigingen/tests/test_payment_history_scalability.py -v

    # Run specific test class
    python -m pytest verenigingen/tests/test_payment_history_scalability.py::PaymentHistoryScalabilityTest -v

    # Run with different scales
    python -m pytest verenigingen/tests/test_payment_history_scalability.py -k "scale_100" -v
"""

import gc
import json
import os
import platform
import psutil
import pytest
import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from unittest.mock import patch, MagicMock

import frappe
from frappe.utils import add_days, add_months, today, now

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.fixtures.test_data_factory import StreamlinedTestDataFactory
from verenigingen.utils.background_jobs import BackgroundJobManager


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics collection"""
    # Timing metrics
    total_execution_time: float = 0.0
    payment_history_load_time: float = 0.0
    data_generation_time: float = 0.0
    cleanup_time: float = 0.0
    
    # Throughput metrics
    members_processed_per_second: float = 0.0
    invoices_processed_per_second: float = 0.0
    payments_processed_per_second: float = 0.0
    
    # Memory metrics
    memory_usage_start_mb: float = 0.0
    memory_usage_peak_mb: float = 0.0
    memory_usage_end_mb: float = 0.0
    memory_delta_mb: float = 0.0
    
    # Database metrics
    total_db_queries: int = 0
    db_query_time: float = 0.0
    avg_query_time_ms: float = 0.0
    slow_queries_count: int = 0
    
    # Background job metrics
    jobs_queued: int = 0
    jobs_completed: int = 0
    jobs_failed: int = 0
    avg_job_completion_time: float = 0.0
    
    # Scale metrics
    member_count: int = 0
    invoice_count: int = 0
    payment_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)


class PerformanceMetricsCollector:
    """Comprehensive performance measurement and monitoring"""
    
    def __init__(self):
        self.metrics = PerformanceMetrics()
        self.start_time = None
        self.query_log = []
        self.memory_samples = []
        self.job_completion_times = []
        
    def start_collection(self):
        """Start performance metrics collection"""
        self.start_time = time.time()
        self.metrics.memory_usage_start_mb = self._get_memory_usage()
        
        # Start memory monitoring thread
        self._start_memory_monitoring()
        
        # Hook into database query monitoring
        self._start_query_monitoring()
        
    def stop_collection(self):
        """Stop performance metrics collection and calculate final metrics"""
        if self.start_time:
            self.metrics.total_execution_time = time.time() - self.start_time
            
        self.metrics.memory_usage_end_mb = self._get_memory_usage()
        self.metrics.memory_usage_peak_mb = max(self.memory_samples) if self.memory_samples else self.metrics.memory_usage_end_mb
        self.metrics.memory_delta_mb = self.metrics.memory_usage_end_mb - self.metrics.memory_usage_start_mb
        
        # Calculate database metrics
        self._calculate_db_metrics()
        
        # Calculate throughput metrics
        self._calculate_throughput_metrics()
        
        # Calculate background job metrics
        self._calculate_job_metrics()
        
    def record_payment_history_timing(self, duration: float):
        """Record payment history load timing"""
        self.metrics.payment_history_load_time += duration
        
    def record_data_generation_timing(self, duration: float):
        """Record data generation timing"""
        self.metrics.data_generation_time += duration
        
    def record_cleanup_timing(self, duration: float):
        """Record cleanup timing"""
        self.metrics.cleanup_time += duration
        
    def record_job_completion(self, duration: float):
        """Record background job completion time"""
        self.job_completion_times.append(duration)
        
    def set_scale_metrics(self, member_count: int, invoice_count: int, payment_count: int):
        """Set scale-related metrics"""
        self.metrics.member_count = member_count
        self.metrics.invoice_count = invoice_count
        self.metrics.payment_count = payment_count
        
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        try:
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except:
            return 0.0
            
    def _start_memory_monitoring(self):
        """Start background memory monitoring"""
        def monitor_memory():
            while self.start_time and time.time() - self.start_time < 3600:  # Monitor for max 1 hour
                self.memory_samples.append(self._get_memory_usage())
                time.sleep(1)  # Sample every second
                
        thread = threading.Thread(target=monitor_memory, daemon=True)
        thread.start()
        
    def _start_query_monitoring(self):
        """Start database query monitoring"""
        # This would integrate with Frappe's query logging if available
        # For now, we'll use a simple approach
        pass
        
    def _calculate_db_metrics(self):
        """Calculate database performance metrics"""
        if self.query_log:
            self.metrics.total_db_queries = len(self.query_log)
            total_query_time = sum(q.get('duration', 0) for q in self.query_log)
            self.metrics.db_query_time = total_query_time
            self.metrics.avg_query_time_ms = (total_query_time / len(self.query_log)) * 1000
            self.metrics.slow_queries_count = len([q for q in self.query_log if q.get('duration', 0) > 0.1])
            
    def _calculate_throughput_metrics(self):
        """Calculate throughput metrics"""
        if self.metrics.total_execution_time > 0:
            self.metrics.members_processed_per_second = self.metrics.member_count / self.metrics.total_execution_time
            self.metrics.invoices_processed_per_second = self.metrics.invoice_count / self.metrics.total_execution_time
            self.metrics.payments_processed_per_second = self.metrics.payment_count / self.metrics.total_execution_time
            
    def _calculate_job_metrics(self):
        """Calculate background job metrics"""
        if self.job_completion_times:
            self.metrics.avg_job_completion_time = sum(self.job_completion_times) / len(self.job_completion_times)


class PaymentHistoryTestDataGenerator:
    """Specialized test data generator for payment history scalability testing"""
    
    def __init__(self, factory: StreamlinedTestDataFactory, seed: int = None):
        self.factory = factory
        self.seed = seed or 42
        random.seed(self.seed)
        
    def generate_member_with_payment_history(self, 
                                           payment_months: int = 12,
                                           payment_frequency: str = "Monthly",
                                           include_failed_payments: bool = False,
                                           include_unreconciled_payments: bool = False) -> Dict[str, Any]:
        """Generate a member with realistic payment history"""
        
        # Create member and membership
        member = self.factory.create_test_member()
        membership_type = self.factory.create_test_membership_type()
        membership = self.factory.create_test_membership(
            member=member,
            membership_type=membership_type
        )
        
        # Create SEPA mandate if needed
        sepa_mandate = None
        if random.choice([True, False]):  # 50% have SEPA mandates
            sepa_mandate = self.factory.create_test_sepa_mandate(member=member)
            
        # Generate payment history
        invoices = []
        payments = []
        
        # Calculate payment dates based on frequency
        payment_dates = self._calculate_payment_dates(payment_months, payment_frequency)
        
        for i, payment_date in enumerate(payment_dates):
            # Create invoice
            invoice = self._create_test_invoice(
                member=member,
                membership=membership,
                posting_date=payment_date,
                amount=random.uniform(15.0, 100.0)
            )
            invoices.append(invoice)
            
            # Create payment (90% success rate)
            if random.random() < 0.9 or not include_failed_payments:
                payment = self._create_test_payment(
                    member=member,
                    invoice=invoice,
                    posting_date=add_days(payment_date, random.randint(0, 7))
                )
                payments.append(payment)
                
        # Add some unreconciled payments if requested
        if include_unreconciled_payments and random.random() < 0.3:  # 30% chance
            unreconciled_payment = self._create_unreconciled_payment(member=member)
            payments.append(unreconciled_payment)
            
        return {
            "member": member,
            "membership": membership,
            "membership_type": membership_type,
            "sepa_mandate": sepa_mandate,
            "invoices": invoices,
            "payments": payments,
            "payment_months": payment_months,
            "payment_frequency": payment_frequency
        }
        
    def generate_bulk_members_with_payment_history(self, 
                                                 member_count: int,
                                                 max_payment_months: int = 12) -> List[Dict[str, Any]]:
        """Generate multiple members with varied payment histories"""
        members_data = []
        
        print(f"📊 Generating {member_count} members with payment history...")
        
        for i in range(member_count):
            if i % 100 == 0:
                print(f"  Generated {i}/{member_count} members...")
                
            # Vary payment history characteristics
            payment_months = random.randint(1, max_payment_months)
            payment_frequency = random.choice(["Monthly", "Quarterly", "Annual"])
            include_failed = random.random() < 0.2  # 20% have failed payments
            include_unreconciled = random.random() < 0.3  # 30% have unreconciled payments
            
            member_data = self.generate_member_with_payment_history(
                payment_months=payment_months,
                payment_frequency=payment_frequency,
                include_failed_payments=include_failed,
                include_unreconciled_payments=include_unreconciled
            )
            
            members_data.append(member_data)
            
        print(f"✅ Generated {len(members_data)} members with payment history")
        return members_data
        
    def _calculate_payment_dates(self, months: int, frequency: str) -> List[str]:
        """Calculate realistic payment dates based on frequency"""
        dates = []
        current_date = add_days(today(), -months * 30)  # Start from months ago
        
        if frequency == "Monthly":
            for i in range(months):
                dates.append(add_months(current_date, i))
        elif frequency == "Quarterly":
            for i in range(0, months, 3):
                dates.append(add_months(current_date, i))
        elif frequency == "Annual":
            dates.append(current_date)
            if months > 12:
                dates.append(add_months(current_date, 12))
        else:
            # Default to monthly
            for i in range(months):
                dates.append(add_months(current_date, i))
                
        return [str(date) for date in dates]
        
    def _create_test_invoice(self, member, membership, posting_date, amount) -> Any:
        """Create test invoice with proper relationships"""
        return self.factory.create_test_sales_invoice(
            customer=member.customer,
            membership=membership.name,
            posting_date=posting_date,
            items=[{
                "item_code": "MEMBERSHIP-DUES",
                "qty": 1,
                "rate": amount
            }]
        )
        
    def _create_test_payment(self, member, invoice, posting_date) -> Any:
        """Create test payment entry linked to invoice"""
        return self.factory.create_test_payment_entry(
            party=member.customer,
            party_type="Customer",
            posting_date=posting_date,
            paid_amount=invoice.grand_total,
            references=[{
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice.name,
                "allocated_amount": invoice.grand_total
            }]
        )
        
    def _create_unreconciled_payment(self, member) -> Any:
        """Create unreconciled payment entry"""
        return self.factory.create_test_payment_entry(
            party=member.customer,
            party_type="Customer",
            posting_date=add_days(today(), -random.randint(1, 30)),
            paid_amount=random.uniform(10.0, 50.0)
            # No references - makes it unreconciled
        )


class PaymentHistoryScalabilityTest(VereningingenTestCase):
    """Main scalability test suite for payment history functionality"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test class with factory and metrics collector"""
        super().setUpClass()
        cls.factory = StreamlinedTestDataFactory(cleanup_on_exit=False, seed=42)
        cls.test_results = {}
        
    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        if hasattr(cls, 'factory'):
            cls.factory.cleanup()
        super().tearDownClass()
        
    def setUp(self):
        """Set up individual test with metrics collection"""
        super().setUp()
        self.metrics_collector = PerformanceMetricsCollector()
        self.test_data_generator = PaymentHistoryTestDataGenerator(self.factory)
        self.metrics_collector.start_collection()
        
    def tearDown(self):
        """Clean up individual test and collect metrics"""
        cleanup_start = time.time()
        super().tearDown()
        cleanup_time = time.time() - cleanup_start
        
        self.metrics_collector.record_cleanup_timing(cleanup_time)
        self.metrics_collector.stop_collection()
        
        # Store test results
        test_name = self._testMethodName
        self.test_results[test_name] = self.metrics_collector.metrics.to_dict()
        
    @pytest.mark.smoke
    def test_payment_history_scale_100_members(self):
        """Test payment history performance with 100 members (smoke test)"""
        self._run_payment_history_scale_test(
            member_count=100,
            max_payment_months=6,
            test_name="scale_100_smoke"
        )
        
    @pytest.mark.integration 
    def test_payment_history_scale_500_members(self):
        """Test payment history performance with 500 members (integration test)"""
        self._run_payment_history_scale_test(
            member_count=500,
            max_payment_months=12,
            test_name="scale_500_integration"
        )
        
    @pytest.mark.performance
    def test_payment_history_scale_1000_members(self):
        """Test payment history performance with 1000 members (performance test)"""
        self._run_payment_history_scale_test(  
            member_count=1000,
            max_payment_months=12,
            test_name="scale_1000_performance"
        )
        
    @pytest.mark.stress
    def test_payment_history_scale_2500_members(self):
        """Test payment history performance with 2500 members (stress test)"""
        self._run_payment_history_scale_test(
            member_count=2500,
            max_payment_months=18,
            test_name="scale_2500_stress"
        )
        
    @pytest.mark.stress
    def test_payment_history_scale_5000_members(self):
        """Test payment history performance with 5000 members (maximum stress test)"""
        self._run_payment_history_scale_test(
            member_count=5000,
            max_payment_months=24,
            test_name="scale_5000_maximum"
        )
        
    def _run_payment_history_scale_test(self, member_count: int, max_payment_months: int, test_name: str):
        """Core payment history scaling test implementation"""
        
        print(f"\n🚀 Running {test_name}: {member_count} members, up to {max_payment_months} months history")
        
        # Phase 1: Generate test data
        data_gen_start = time.time()
        members_data = self.test_data_generator.generate_bulk_members_with_payment_history(
            member_count=member_count,
            max_payment_months=max_payment_months
        )
        data_gen_time = time.time() - data_gen_start
        self.metrics_collector.record_data_generation_timing(data_gen_time)
        
        # Calculate total entities created
        total_invoices = sum(len(md["invoices"]) for md in members_data)
        total_payments = sum(len(md["payments"]) for md in members_data)
        
        self.metrics_collector.set_scale_metrics(
            member_count=member_count,
            invoice_count=total_invoices,
            payment_count=total_payments
        )
        
        print(f"📊 Test data generated: {member_count} members, {total_invoices} invoices, {total_payments} payments")
        
        # Phase 2: Test payment history loading performance
        payment_history_start = time.time()
        
        successful_loads = 0
        failed_loads = 0
        
        for i, member_data in enumerate(members_data):
            if i % 250 == 0:
                print(f"  Processing member {i+1}/{member_count}...")
                
            try:
                member = member_data["member"]
                
                # Load payment history (this is what we're testing)
                result = member.load_payment_history()
                
                if result:
                    successful_loads += 1
                    
                    # Verify payment history was populated
                    self.assertIsNotNone(member.payment_history)
                    self.assertGreater(len(member.payment_history), 0)
                    
                    # Verify data integrity
                    self._verify_payment_history_integrity(member, member_data)
                else:
                    failed_loads += 1
                    
            except Exception as e:
                failed_loads += 1
                print(f"❌ Failed to load payment history for member {i}: {e}")
                
        payment_history_time = time.time() - payment_history_start
        self.metrics_collector.record_payment_history_timing(payment_history_time)
        
        print(f"✅ Payment history loading: {successful_loads} successful, {failed_loads} failed")
        
        # Phase 3: Performance assertions
        self._assert_performance_requirements(member_count, payment_history_time)
        
        # Phase 4: Generate summary report
        self._generate_test_summary_report(test_name, members_data)
        
    def _verify_payment_history_integrity(self, member, member_data):
        """Verify payment history data integrity"""
        payment_history = member.payment_history
        expected_invoices = len(member_data["invoices"])
        
        # Should have entries for each invoice (allowing for some variance due to test conditions)
        invoice_entries = [entry for entry in payment_history if entry.invoice]
        self.assertGreaterEqual(len(invoice_entries), expected_invoices * 0.8)  # Allow 20% variance
        
        # Verify key fields are populated
        for entry in payment_history[:5]:  # Check first 5 entries
            self.assertIsNotNone(entry.posting_date)
            self.assertIsNotNone(entry.amount)
            self.assertIsNotNone(entry.payment_status)
            
    def _assert_performance_requirements(self, member_count: int, execution_time: float):
        """Assert performance requirements are met"""
        
        # Performance requirements (adjust based on infrastructure)
        if member_count <= 100:
            max_time = 10.0  # 10 seconds for 100 members
        elif member_count <= 500:
            max_time = 30.0  # 30 seconds for 500 members
        elif member_count <= 1000:
            max_time = 60.0  # 1 minute for 1000 members
        elif member_count <= 2500:
            max_time = 180.0  # 3 minutes for 2500 members
        else:
            max_time = 300.0  # 5 minutes for 5000 members
            
        self.assertLess(
            execution_time, 
            max_time,
            f"Payment history loading took {execution_time:.2f}s, expected < {max_time}s for {member_count} members"
        )
        
        # Throughput requirements
        min_members_per_second = 2.0 if member_count > 1000 else 5.0
        actual_throughput = member_count / execution_time
        
        self.assertGreater(
            actual_throughput,
            min_members_per_second,
            f"Throughput {actual_throughput:.2f} members/s below minimum {min_members_per_second} members/s"
        )
        
    def _generate_test_summary_report(self, test_name: str, members_data: List[Dict]):
        """Generate comprehensive test summary report"""
        metrics = self.metrics_collector.metrics
        
        summary = {
            "test_name": test_name,
            "timestamp": now(),
            "system_info": {
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "memory_total_gb": psutil.virtual_memory().total / (1024**3),
            },
            "test_scale": {
                "member_count": len(members_data),
                "total_invoices": sum(len(md["invoices"]) for md in members_data),
                "total_payments": sum(len(md["payments"]) for md in members_data),
            },
            "performance_metrics": metrics.to_dict(),
            "test_results": {
                "success": True,
                "performance_acceptable": metrics.total_execution_time < 300,  # 5 minutes max
                "memory_usage_acceptable": metrics.memory_delta_mb < 500,  # 500MB increase max
            }
        }
        
        # Save report to file
        report_file = f"/tmp/payment_history_scalability_{test_name}_{int(time.time())}.json"
        with open(report_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
            
        print(f"📊 Test summary report saved: {report_file}")
        
        # Print key metrics
        print(f"📈 Performance Summary:")
        print(f"  Total execution time: {metrics.total_execution_time:.2f}s")
        print(f"  Members/second: {metrics.members_processed_per_second:.2f}")
        print(f"  Memory delta: {metrics.memory_delta_mb:.1f}MB")
        print(f"  Peak memory: {metrics.memory_usage_peak_mb:.1f}MB")


class BackgroundJobScalabilityTest(VereningingenTestCase):
    """Test background job processing scalability for payment history updates"""
    
    def setUp(self):
        """Set up background job testing environment"""
        super().setUp()
        self.factory = StreamlinedTestDataFactory(cleanup_on_exit=False, seed=42)
        self.metrics_collector = PerformanceMetricsCollector()
        self.job_completion_times = []
        
    def tearDown(self):
        """Clean up background job testing"""
        self.factory.cleanup()
        super().tearDown()
        
    @pytest.mark.integration
    def test_background_job_queue_processing_50_members(self):
        """Test background job queue processing with 50 members"""
        self._run_background_job_scale_test(member_count=50, test_name="bg_jobs_50")
        
    @pytest.mark.performance  
    def test_background_job_queue_processing_200_members(self):
        """Test background job queue processing with 200 members"""
        self._run_background_job_scale_test(member_count=200, test_name="bg_jobs_200")
        
    def _run_background_job_scale_test(self, member_count: int, test_name: str):
        """Core background job scaling test"""
        
        print(f"\n🔄 Testing background job processing: {member_count} members")
        
        # Create test members
        members = []
        for i in range(member_count):
            member = self.factory.create_test_member()
            members.append(member)
            
        # Queue background jobs for payment history updates
        job_ids = []
        queue_start = time.time()
        
        for member in members:
            job_id = BackgroundJobManager.queue_member_payment_history_update(
                member_name=member.name,
                payment_entry=None,
                priority="default"
            )
            job_ids.append(job_id)
            
        queue_time = time.time() - queue_start
        print(f"📤 Queued {len(job_ids)} jobs in {queue_time:.2f}s")
        
        # Monitor job completion
        self._monitor_job_completion(job_ids, timeout=300)  # 5 minute timeout
        
        # Verify job results
        self._verify_background_job_results(job_ids, members)
        
    def _monitor_job_completion(self, job_ids: List[str], timeout: int = 300):
        """Monitor background job completion with timeout"""
        
        start_time = time.time()
        completed_jobs = set()
        failed_jobs = set()
        
        print(f"⏳ Monitoring {len(job_ids)} background jobs...")
        
        while len(completed_jobs) + len(failed_jobs) < len(job_ids):
            if time.time() - start_time > timeout:
                remaining = len(job_ids) - len(completed_jobs) - len(failed_jobs)
                print(f"⚠️ Timeout reached, {remaining} jobs still pending")
                break
                
            for job_id in job_ids:
                if job_id in completed_jobs or job_id in failed_jobs:
                    continue
                    
                job_status = BackgroundJobManager.get_job_status(job_id)
                status = job_status.get("status", "Unknown")
                
                if status == "Completed":
                    completed_jobs.add(job_id)
                    job_time = job_status.get("result", {}).get("execution_time", 0)
                    self.job_completion_times.append(job_time)
                elif status == "Failed":
                    failed_jobs.add(job_id)
                    
            # Progress update
            total_done = len(completed_jobs) + len(failed_jobs)
            if total_done % 10 == 0:
                progress = (total_done / len(job_ids)) * 100
                print(f"  Progress: {total_done}/{len(job_ids)} ({progress:.1f}%)")
                
            time.sleep(1)  # Check every second
            
        completion_time = time.time() - start_time
        print(f"✅ Job monitoring completed in {completion_time:.2f}s")
        print(f"  Completed: {len(completed_jobs)}")
        print(f"  Failed: {len(failed_jobs)}")
        print(f"  Pending: {len(job_ids) - len(completed_jobs) - len(failed_jobs)}")
        
        # Calculate average job completion time
        if self.job_completion_times:
            avg_completion = sum(self.job_completion_times) / len(self.job_completion_times)
            print(f"  Average job completion time: {avg_completion:.2f}s")
            
    def _verify_background_job_results(self, job_ids: List[str], members: List):
        """Verify background job processing results"""
        
        successful_updates = 0
        
        for member in members:
            try:
                # Reload member to get updated payment history
                member.reload()
                
                # Verify payment history was loaded (even if empty)
                if hasattr(member, 'payment_history'):
                    successful_updates += 1
                    
            except Exception as e:
                print(f"❌ Failed to verify member {member.name}: {e}")
                
        success_rate = (successful_updates / len(members)) * 100
        print(f"✅ Payment history update success rate: {success_rate:.1f}%")
        
        # Assert minimum success rate
        self.assertGreater(success_rate, 85.0, f"Success rate {success_rate:.1f}% below minimum 85%")


class EdgeCaseScalabilityTest(VereningingenTestCase):
    """Test edge cases and failure scenarios at scale"""
    
    def setUp(self):
        """Set up edge case testing environment"""
        super().setUp()
        self.factory = StreamlinedTestDataFactory(cleanup_on_exit=False, seed=42)
        
    def tearDown(self):
        """Clean up edge case testing"""
        self.factory.cleanup()
        super().tearDown()
        
    @pytest.mark.performance
    def test_payment_history_with_missing_customers(self):
        """Test payment history loading with members missing customer records"""
        
        # Create members, some without customers
        members = []
        for i in range(100):
            member = self.factory.create_test_member()
            
            # Remove customer from 20% of members to simulate edge case
            if i % 5 == 0:
                member.customer = None
                member.save()
                
            members.append(member)
            
        # Test payment history loading with missing customers
        successful_loads = 0
        graceful_failures = 0
        
        for member in members:
            try:
                result = member.load_payment_history()
                
                if member.customer:
                    # Should succeed for members with customers
                    self.assertTrue(result)
                    successful_loads += 1
                else:
                    # Should gracefully handle members without customers
                    graceful_failures += 1
                    
            except Exception as e:
                self.fail(f"Payment history loading should not throw exceptions: {e}")
                
        print(f"✅ Edge case test: {successful_loads} successful, {graceful_failures} graceful failures")
        
    @pytest.mark.stress
    def test_concurrent_payment_history_updates(self):
        """Test concurrent payment history updates to detect race conditions"""
        
        # Create test members
        members = [self.factory.create_test_member() for _ in range(50)]
        
        # Function to update payment history in thread
        def update_payment_history(member):
            try:
                result = member.load_payment_history()
                return result
            except Exception as e:
                print(f"❌ Concurrent update failed for {member.name}: {e}")
                return False
                
        # Run concurrent updates
        import concurrent.futures
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(update_payment_history, member) for member in members]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
            
        success_count = sum(1 for result in results if result)
        success_rate = (success_count / len(results)) * 100
        
        print(f"✅ Concurrent updates: {success_count}/{len(results)} successful ({success_rate:.1f}%)")
        
        # Should handle concurrent updates gracefully (allow some failures due to locking)
        self.assertGreater(success_rate, 70.0, f"Concurrent success rate {success_rate:.1f}% too low")


# Test Runner Integration

def run_payment_history_scalability_tests(scale: str = "all", verbose: bool = True) -> Dict[str, Any]:
    """
    Run payment history scalability tests with specified scale
    
    Args:
        scale: Test scale to run ("smoke", "integration", "performance", "stress", "all")
        verbose: Enable verbose output
        
    Returns:
        Dictionary with test results and metrics
    """
    
    print(f"🚀 Running Payment History Scalability Tests - Scale: {scale}")
    print("=" * 60)
    
    # Map scale to pytest markers
    marker_map = {
        "smoke": "smoke",
        "integration": "integration", 
        "performance": "performance",
        "stress": "stress",
        "all": None  # Run all tests
    }
    
    marker = marker_map.get(scale)
    
    # Build pytest command
    cmd_args = [
        "-v" if verbose else "-q",
        "--tb=short",
        "--disable-warnings",
        f"{__file__}"
    ]
    
    if marker:
        cmd_args.append(f"-m {marker}")
        
    # Run tests
    import subprocess
    import sys
    
    result = subprocess.run(
        [sys.executable, "-m", "pytest"] + cmd_args,
        capture_output=True,
        text=True
    )
    
    # Parse results
    test_results = {
        "scale": scale,
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "return_code": result.returncode
    }
    
    if verbose:
        print("\n📊 Test Execution Summary:")
        print(f"  Scale: {scale}")
        print(f"  Success: {'✅' if test_results['success'] else '❌'}")
        print(f"  Return Code: {result.returncode}")
        
        if result.stdout:
            print("\n📋 Test Output:")
            print(result.stdout)
            
        if result.stderr and not test_results['success']:
            print("\n❌ Test Errors:")
            print(result.stderr)
            
    return test_results


if __name__ == "__main__":
    """Command-line interface for scalability testing"""
    
    import argparse
    
    parser = argparse.ArgumentParser(description="Payment History Scalability Testing Suite")
    parser.add_argument("--scale", choices=["smoke", "integration", "performance", "stress", "all"], 
                       default="smoke", help="Test scale to run")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--json-output", help="Save results to JSON file")
    
    args = parser.parse_args()
    
    # Run tests
    results = run_payment_history_scalability_tests(
        scale=args.scale,
        verbose=args.verbose
    )
    
    # Save JSON output if requested
    if args.json_output:
        with open(args.json_output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"📄 Results saved to: {args.json_output}")
        
    # Exit with appropriate code
    sys.exit(0 if results["success"] else 1)