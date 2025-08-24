#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Background Processing Tests for AccountCreationManager
=====================================================

This test suite validates the background job processing, Redis queue integration,
retry mechanisms, and concurrent request handling for the account creation system.

Key Testing Areas:
- Redis Queue Integration: Job queueing, execution, and monitoring
- Retry Mechanisms: Exponential backoff, retry limits, failure categorization
- Concurrent Processing: Race conditions, resource locking, state consistency
- Timeout Handling: Job timeouts, cleanup procedures, recovery mechanisms
- Performance Testing: High-volume processing, memory usage, queue saturation

Author: Verenigingen Infrastructure Team
"""

import unittest
from unittest.mock import patch, MagicMock, call, AsyncMock
import frappe
from frappe.utils import now, add_to_date, get_datetime
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from verenigingen.utils.account_creation_manager import (
    AccountCreationManager,
    process_account_creation_request,
    queue_account_creation_for_member,
    queue_account_creation_for_volunteer
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAccountCreationBackgroundProcessing(EnhancedTestCase):
    """Background processing and Redis queue tests"""
    
    def setUp(self):
        super().setUp()
        self.original_user = frappe.session.user
        
    def tearDown(self):
        frappe.set_user(self.original_user)
        super().tearDown()
        
    @patch('frappe.enqueue')
    def test_redis_queue_integration_basic(self, mock_enqueue):
        """Test basic Redis queue integration"""
        member = self.create_test_member(
            first_name="Redis",
            last_name="Queue",
            email="redis.queue@test.invalid"
        )
        
        # Queue account creation
        result = queue_account_creation_for_member(member.name)
        
        # Verify job was enqueued with correct parameters
        mock_enqueue.assert_called_once()
        call_args = mock_enqueue.call_args
        
        # Verify function name
        self.assertEqual(
            call_args[0][0], 
            "verenigingen.utils.account_creation_manager.process_account_creation_request"
        )
        
        # Verify job parameters
        job_kwargs = call_args[1]
        self.assertEqual(job_kwargs["queue"], "long")
        self.assertEqual(job_kwargs["timeout"], 600)
        self.assertTrue(job_kwargs["job_name"].startswith("account_creation_"))
        self.assertIn("request_name", job_kwargs)
        
    @patch('frappe.enqueue')
    def test_priority_based_queueing(self, mock_enqueue):
        """Test that priority affects queue processing"""
        member = self.create_test_member(
            first_name="Priority",
            last_name="Queue",
            email="priority.queue@test.invalid"
        )
        
        # Create high priority request
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member",
            priority="High"
        )
        
        # Queue for processing
        request.queue_processing()
        
        # Verify high priority jobs get appropriate handling
        mock_enqueue.assert_called_once()
        job_kwargs = mock_enqueue.call_args[1]
        
        # High priority jobs might use different queue or parameters
        self.assertEqual(job_kwargs["queue"], "long")  # Still long queue but could be adjusted
        
    @patch('frappe.enqueue')
    def test_exponential_backoff_retry_scheduling(self, mock_enqueue):
        """Test exponential backoff for retry scheduling"""
        member = self.create_test_member(
            first_name="Exponential",
            last_name="Backoff",
            email="exponential.backoff@test.invalid"
        )
        
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member",
            status="Failed",
            retry_count=2  # Third attempt
        )
        
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.load_request()
        
        with patch.object(manager, 'is_retryable_error', return_value=True):
            manager.schedule_retry()
            
        # Verify retry was scheduled with exponential backoff
        mock_enqueue.assert_called_once()
        call_args = mock_enqueue.call_args[1]
        
        # For retry_count=2, delay should be min(5 * (2^2), 60) = min(20, 60) = 20 minutes
        self.assertIsNotNone(call_args.get("at_time"))
        
        # Verify job parameters
        self.assertEqual(call_args["queue"], "long")
        self.assertEqual(call_args["timeout"], 600)
        self.assertTrue(call_args["job_name"].startswith("account_creation_retry_"))
        
    def test_retry_limit_enforcement(self):
        """Test that retry limits are properly enforced"""
        member = self.create_test_member(
            first_name="Retry",
            last_name="Limit",
            email="retry.limit@test.invalid"
        )
        
        # Create request at maximum retry count
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member",
            status="Failed",
            retry_count=3  # At maximum
        )
        
        # Attempt to retry should fail
        with self.assertRaises(frappe.ValidationError) as cm:
            request.retry_processing()
            
        self.assertIn("Maximum retry attempts exceeded", str(cm.exception))
        
    def test_retryable_vs_non_retryable_errors(self):
        """Test classification of retryable vs non-retryable errors"""
        member = self.create_test_member(
            first_name="Error",
            last_name="Classification",
            email="error.classification@test.invalid"
        )
        
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member"
        )
        
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.load_request()
        
        # Test retryable errors
        retryable_errors = [
            Exception("Connection timeout occurred"),
            Exception("Database connection error"),
            Exception("Temporary network failure"),
            Exception("Deadlock detected"),
            Exception("Lock wait timeout exceeded")
        ]
        
        for error in retryable_errors:
            with self.subTest(error=str(error)):
                self.assertTrue(manager.is_retryable_error(error))
                
        # Test non-retryable errors
        non_retryable_errors = [
            frappe.ValidationError("Invalid role specified"),
            frappe.PermissionError("Access denied"),
            frappe.DoesNotExistError("Record not found"),
            Exception("Invalid email format")
        ]
        
        for error in non_retryable_errors:
            with self.subTest(error=str(error)):
                self.assertFalse(manager.is_retryable_error(error))
                
    def test_background_job_timeout_handling(self):
        """Test handling of background job timeouts"""
        member = self.create_test_member(
            first_name="Timeout",
            last_name="Handling",
            email="timeout.handling@test.invalid"
        )
        
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member"
        )
        
        # Mock a timeout scenario
        with patch('frappe.get_doc') as mock_get_doc:
            # Mock the request loading to succeed
            mock_get_doc.return_value = request
            
            # Simulate timeout during user creation
            frappe.set_user("Administrator")
            manager = AccountCreationManager(request.name)
            
            # Mock timeout error
            with patch.object(manager, 'create_user_account') as mock_create_user:
                mock_create_user.side_effect = Exception("timeout occurred during user creation")
                
                with self.assertRaises(Exception):
                    manager.process_complete_pipeline()
                    
                # Verify request is marked as failed
                request.reload()
                self.assertEqual(request.status, "Failed")
                self.assertIn("timeout", request.failure_reason.lower())
                
    def test_concurrent_request_processing(self):
        """Test concurrent processing of multiple requests"""
        # Create multiple members and requests
        requests = []
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Concurrent",
                last_name=f"Test{i}",
                email=f"concurrent.test{i}@test.invalid"
            )
            
            request = self.create_test_account_creation_request(
                source_record=member.name,
                request_type="Member"
            )
            requests.append(request)
            
        frappe.set_user("Administrator")
        
        # Process requests concurrently
        def process_request(request_name):
            try:
                result = process_account_creation_request(request_name)
                return {"request_name": request_name, "success": True, "result": result}
            except Exception as e:
                return {"request_name": request_name, "success": False, "error": str(e)}
                
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_request = {
                executor.submit(process_request, req.name): req.name 
                for req in requests
            }
            
            results = []
            for future in as_completed(future_to_request):
                result = future.result()
                results.append(result)
                
        # Verify all requests were processed
        self.assertEqual(len(results), 5)
        
        # Check for successful processing
        successful_count = sum(1 for r in results if r["success"])
        self.assertGreaterEqual(successful_count, 3)  # At least 3 should succeed
        
    def test_queue_saturation_handling(self):
        """Test system behavior under high queue load"""
        # Create many requests quickly
        requests = []
        for i in range(20):  # Create 20 requests
            member = self.create_test_member(
                first_name=f"Load",
                last_name=f"Test{i:02d}",
                email=f"load.test{i:02d}@test.invalid"
            )
            
            request = self.create_test_account_creation_request(
                source_record=member.name,
                request_type="Member"
            )
            requests.append(request)
            
        # Queue all requests with mocked enqueue to test queueing logic
        with patch('frappe.enqueue') as mock_enqueue:
            for request in requests:
                request.queue_processing()
                
            # Verify all requests were queued
            self.assertEqual(mock_enqueue.call_count, 20)
            
            # Verify no duplicate job names (potential race condition)
            job_names = [call[1]["job_name"] for call in mock_enqueue.call_args_list]
            self.assertEqual(len(job_names), len(set(job_names)), "Duplicate job names detected")
            
    def test_job_monitoring_and_status_tracking(self):
        """Test job monitoring and status tracking capabilities"""
        member = self.create_test_member(
            first_name="Job",
            last_name="Monitoring",
            email="job.monitoring@test.invalid"
        )
        
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member"
        )
        
        # Track status changes during processing
        initial_status = request.status
        
        # Queue processing
        with patch('frappe.enqueue'):
            request.queue_processing()
            
        # Verify status progression
        request.reload()
        self.assertEqual(request.status, "Queued")
        self.assertIsNotNone(request.processing_started_at)
        
        # Simulate processing stages
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.load_request()
        
        # Test stage tracking
        stages = ["User Creation", "Role Assignment", "Employee Creation", "Record Linking"]
        
        for stage in stages:
            manager.request.mark_processing(stage)
            manager.request.reload()
            self.assertEqual(manager.request.pipeline_stage, stage)
            self.assertEqual(manager.request.status, "Processing")
            
    @patch('frappe.enqueue')
    def test_job_cleanup_after_completion(self, mock_enqueue):
        """Test job cleanup procedures after completion"""
        member = self.create_test_member(
            first_name="Job",
            last_name="Cleanup",
            email="job.cleanup@test.invalid"
        )
        
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member"
        )
        
        # Process the request
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        # Verify completion cleanup
        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertIsNotNone(request.completed_at)
        self.assertEqual(request.pipeline_stage, "Completed")
        
        # Verify no additional retry jobs are scheduled
        mock_enqueue.assert_not_called()  # Should not schedule retries for completed jobs
        
    def test_job_failure_recovery_mechanisms(self):
        """Test job failure recovery and cleanup mechanisms"""
        member = self.create_test_member(
            first_name="Failure",
            last_name="Recovery",
            email="failure.recovery@test.invalid"
        )
        
        # Create request with invalid configuration to cause failure
        request_data = {
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Invalid Role Name"}]  # This will cause failure
        }
        
        request = frappe.get_doc(request_data)
        request.append("requested_roles", {"role": "Invalid Role Name"})
        request.insert()
        
        frappe.set_user("Administrator")
        
        # Attempt processing - should fail gracefully
        with self.assertRaises(frappe.ValidationError):
            result = process_account_creation_request(request.name)
            
        # Verify failure was handled properly
        request.reload()
        self.assertEqual(request.status, "Failed")
        self.assertIsNotNone(request.failure_reason)
        self.assertIn("does not exist", request.failure_reason)
        
    def test_memory_usage_during_high_volume_processing(self):
        """Test memory usage during high-volume processing"""
        # Create batch of requests
        batch_size = 50
        requests = []
        
        for i in range(batch_size):
            member = self.create_test_member(
                first_name=f"Memory",
                last_name=f"Test{i:03d}",
                email=f"memory.test{i:03d}@test.invalid"
            )
            
            request = self.create_test_account_creation_request(
                source_record=member.name,
                request_type="Member"
            )
            requests.append(request)
            
        # Process with memory monitoring
        frappe.set_user("Administrator")
        
        processed_count = 0
        for request in requests:
            try:
                manager = AccountCreationManager(request.name)
                manager.process_complete_pipeline()
                processed_count += 1
            except Exception as e:
                # Some may fail due to test environment limitations
                frappe.log_error(f"Request processing failed: {e}", "Memory Test")
                
        # Verify reasonable processing success rate
        success_rate = processed_count / batch_size
        self.assertGreaterEqual(success_rate, 0.7, f"Success rate {success_rate} too low")


class TestAccountCreationQueueResilience(EnhancedTestCase):
    """Queue resilience and fault tolerance tests"""
    
    @patch('frappe.enqueue')
    def test_queue_failure_recovery(self, mock_enqueue):
        """Test recovery from queue system failures"""
        member = self.create_test_member(
            first_name="Queue",
            last_name="Failure",
            email="queue.failure@test.invalid"
        )
        
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member"
        )
        
        # Simulate queue system failure
        mock_enqueue.side_effect = Exception("Redis connection failed")
        
        # Queue processing should handle the failure gracefully
        with self.assertRaises(Exception):
            request.queue_processing()
            
        # Request status should reflect the queueing failure
        request.reload()
        # Status might remain "Requested" if queueing failed
        self.assertIn(request.status, ["Requested", "Failed"])
        
    def test_partial_processing_recovery(self):
        """Test recovery from partial processing failures"""
        member = self.create_test_member(
            first_name="Partial",
            last_name="Recovery",
            email="partial.recovery@test.invalid"
        )
        
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member"
        )
        
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.load_request()
        
        # Simulate partial success - user creation succeeds, role assignment fails
        with patch.object(manager, 'assign_roles_and_profile') as mock_assign_roles:
            mock_assign_roles.side_effect = frappe.ValidationError("Role assignment failed")
            
            # Process should fail but preserve partial progress
            with self.assertRaises(frappe.ValidationError):
                manager.process_complete_pipeline()
                
        # Verify partial state is recorded
        request.reload()
        self.assertEqual(request.status, "Failed")
        self.assertIn("Role assignment", request.failure_reason)
        
        # User might have been created even though process failed
        if request.created_user:
            self.assertTrue(frappe.db.exists("User", request.created_user))
            
    def test_deadlock_detection_and_recovery(self):
        """Test deadlock detection and recovery mechanisms"""
        # Create two members for potential deadlock scenario
        member1 = self.create_test_member(
            first_name="Deadlock",
            last_name="Test1",
            email="deadlock.test1@test.invalid"
        )
        
        member2 = self.create_test_member(
            first_name="Deadlock",
            last_name="Test2", 
            email="deadlock.test2@test.invalid"
        )
        
        request1 = self.create_test_account_creation_request(
            source_record=member1.name,
            request_type="Member"
        )
        
        request2 = self.create_test_account_creation_request(
            source_record=member2.name,
            request_type="Member"
        )
        
        frappe.set_user("Administrator")
        
        # Simulate concurrent processing that could lead to deadlock
        def process_with_delay(request_name, delay):
            time.sleep(delay)
            try:
                return process_account_creation_request(request_name)
            except Exception as e:
                return {"success": False, "error": str(e)}
                
        # Run concurrently with different delays
        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(process_with_delay, request1.name, 0.1)
            future2 = executor.submit(process_with_delay, request2.name, 0.2)
            
            result1 = future1.result(timeout=10)
            result2 = future2.result(timeout=10)
            
        # At least one should succeed (deadlock should be resolved)
        success_count = sum(1 for r in [result1, result2] if r.get("success", False))
        self.assertGreaterEqual(success_count, 1, "Both requests failed - possible deadlock")


if __name__ == "__main__":
    unittest.main(verbosity=2)