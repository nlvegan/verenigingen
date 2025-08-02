#!/usr/bin/env python3
"""
Medium Scale Payment History Test
================================

Test payment history performance with medium scale datasets (500-1000 members)
to measure realistic performance under production loads.
"""

import time
import statistics
from datetime import datetime

import frappe
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.scalability.payment_history_test_factory import PaymentHistoryTestFactory
from verenigingen.utils.background_jobs import BackgroundJobManager


class TestMediumScalePaymentHistory(VereningingenTestCase):
    """Test payment history at medium scale for production validation"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.factory = PaymentHistoryTestFactory(cleanup_on_exit=False, seed=42)
        self.test_start_time = time.time()
        
    def tearDown(self):
        """Clean up test data"""
        try:
            print(f"🧹 Starting cleanup...")
            cleanup_start = time.time()
            self.factory.cleanup()
            cleanup_time = time.time() - cleanup_start
            print(f"✅ Cleanup completed in {cleanup_time:.2f}s")
        except Exception as e:
            print(f"Warning: Cleanup error: {e}")
        super().tearDown()
    
    def test_payment_history_creation_500_members(self):
        """Test creating payment history for 500 members - realistic production scale"""
        print("\n🎯 Testing payment history creation with 500 members")
        print("   This represents a realistic medium-scale organization")
        
        start_time = time.time()
        
        # Create medium batch - realistic production scale
        batch_result = self.factory.create_payment_history_batch(
            member_count=500,
            months_history=6,
            avg_payments_per_month=1.5
        )
        
        creation_time = time.time() - start_time
        
        # Validate results
        self.assertEqual(len(batch_result["members"]), 500)
        expected_invoices = 500 * 6 * 1.5  # 4500 expected
        self.assertGreater(len(batch_result["invoices"]), int(expected_invoices * 0.8))  # At least 80%
        self.assertGreater(len(batch_result["payments"]), len(batch_result["invoices"]) * 0.8)  # 80% payment rate
        
        # Performance metrics
        total_records = batch_result["metrics"]["total_records"]
        records_per_second = total_records / creation_time if creation_time > 0 else 0
        
        print(f"✅ Created {total_records} records in {creation_time:.2f}s")
        print(f"📊 Rate: {records_per_second:.1f} records/second")
        print(f"📊 Members per second: {500 / creation_time:.1f}")
        
        # Performance assertions for medium scale
        self.assertLess(creation_time, 300, "Should complete within 5 minutes")
        self.assertGreater(records_per_second, 25, "Should maintain good throughput")
        
        # Test cleanup performance with larger dataset
        cleanup_start = time.time()
        self.factory.cleanup()
        cleanup_time = time.time() - cleanup_start
        
        print(f"🧹 Cleanup performance: {cleanup_time:.2f}s for {total_records} records")
        print(f"📊 Cleanup rate: {total_records / cleanup_time:.1f} records/second")
        
        # Don't run cleanup again in tearDown
        self.factory.created_records = []
        
        return {
            "member_count": 500,
            "total_records": total_records,
            "creation_time": creation_time,
            "records_per_second": records_per_second,
            "cleanup_time": cleanup_time,
            "scale": "medium"
        }
    
    def test_payment_history_batch_processing_200_members(self):
        """Test batch processing performance with 200 members"""
        print("\n🔄 Testing batch payment history processing with 200 members")
        
        # Create test batch
        batch_result = self.factory.create_payment_history_batch(
            member_count=200,
            months_history=4,
            avg_payments_per_month=1.2
        )
        
        print(f"✅ Created test data: {len(batch_result['members'])} members")
        
        # Test batch processing in chunks
        batch_size = 25
        members = batch_result["members"]
        processing_times = []
        total_processed = 0
        
        batch_start = time.time()
        
        for i in range(0, len(members), batch_size):
            chunk_members = members[i:i + batch_size]
            chunk_start = time.time()
            
            # Process this chunk
            for member in chunk_members:
                try:
                    member_doc = frappe.get_doc("Member", member.name)
                    member_doc.load_payment_history()
                    member_doc.save(ignore_permissions=True)
                    total_processed += 1
                except Exception as e:
                    print(f"⚠️ Failed to process member {member.name}: {e}")
            
            chunk_time = time.time() - chunk_start
            processing_times.append(chunk_time)
            
            print(f"  Processed batch {(i//batch_size)+1}: {len(chunk_members)} members in {chunk_time:.2f}s")
        
        total_processing_time = time.time() - batch_start
        avg_batch_time = statistics.mean(processing_times) if processing_times else 0
        
        print(f"✅ Batch processing completed:")
        print(f"   Total processed: {total_processed}/{len(members)} members")
        print(f"   Total time: {total_processing_time:.2f}s")
        print(f"   Average batch time: {avg_batch_time:.2f}s")
        print(f"   Processing rate: {total_processed / total_processing_time:.1f} members/second")
        
        # Performance assertions
        success_rate = total_processed / len(members) if members else 0
        self.assertGreater(success_rate, 0.95, "Should successfully process 95%+ of members")
        self.assertLess(avg_batch_time, 15, "Average batch processing should be reasonable")
        
        return {
            "member_count": len(members),
            "processed_count": total_processed,
            "total_processing_time": total_processing_time,
            "avg_batch_time": avg_batch_time,
            "processing_rate": total_processed / total_processing_time if total_processing_time > 0 else 0,
            "success_rate": success_rate,
            "scale": "medium"
        }
    
    def test_background_job_performance(self):
        """Test background job performance with medium scale"""
        print("\n⚙️ Testing background job processing performance")
        
        # Create smaller batch for job testing
        batch_result = self.factory.create_payment_history_batch(
            member_count=50,
            months_history=3,
            avg_payments_per_month=1.0
        )
        
        # Queue background jobs
        job_ids = []
        queue_start = time.time()
        
        for member in batch_result["members"]:
            job_id = BackgroundJobManager.queue_member_payment_history_update(
                member_name=member.name,
                priority="default"
            )
            if job_id:
                job_ids.append(job_id)
        
        queue_time = time.time() - queue_start
        
        print(f"✅ Queued {len(job_ids)} background jobs in {queue_time:.2f}s")
        print(f"📊 Queue rate: {len(job_ids) / queue_time:.1f} jobs/second")
        
        # Allow processing time
        print("⏳ Waiting for background job processing...")
        time.sleep(15)
        
        # Check job completion
        completed_jobs = 0
        failed_jobs = 0
        
        for job_id in job_ids:
            cache_key = f"job_status_{job_id}"
            job_status = frappe.cache().get_value(cache_key)
            
            if job_status:
                status = job_status.get("status", "unknown")
                if status == "Completed":
                    completed_jobs += 1
                elif status == "Failed":
                    failed_jobs += 1
        
        completion_rate = completed_jobs / len(job_ids) if job_ids else 0
        
        print(f"✅ Background job results:")
        print(f"   Completed: {completed_jobs}/{len(job_ids)}")
        print(f"   Failed: {failed_jobs}/{len(job_ids)}")
        print(f"   Completion rate: {completion_rate:.1%}")
        
        # Assertions for background job performance
        self.assertGreater(len(job_ids), 0, "Should successfully queue jobs")
        self.assertLess(queue_time, 30, "Job queueing should be fast")
        # Note: Background job completion depends on worker availability
        
        return {
            "jobs_queued": len(job_ids),
            "jobs_completed": completed_jobs, 
            "jobs_failed": failed_jobs,
            "queue_time": queue_time,
            "completion_rate": completion_rate,
            "queue_rate": len(job_ids) / queue_time if queue_time > 0 else 0,
            "scale": "medium"
        }